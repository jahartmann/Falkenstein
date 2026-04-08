"""Soul Memory — 3-layer memory system (user / self / relationship)."""
from __future__ import annotations
import json
import datetime
from collections import Counter


_EXTRACT_SYSTEM = (
    "Du analysierst ein Gespraech und extrahierst neue Fakten.\n"
    "Drei Ebenen:\n"
    "- user: Fakten ueber den Nutzer (Vorlieben, Gewohnheiten, Interessen, Kontext)\n"
    "- self: Eigene Erfahrungen/Meinungen der KI\n"
    "- relationship: Beziehungsdynamik zwischen Nutzer und KI\n\n"
    "Kategorien:\n"
    "- user: preferences, interests, habits, relationships, context\n"
    "- self: experiences, opinions, growth, reflections\n"
    "- relationship: dynamics, jokes, history\n\n"
    "Vergleiche mit bestehenden Fakten. Antworte NUR mit JSON-Array:\n"
    '[{"action": "ADD", "layer": "user", "category": "interests", "key": "kurzer_key", "value": "beschreibung"}, ...]\n'
    '[{"action": "UPDATE", "id": 5, "value": "neuer wert"}, ...]\n'
    '[{"action": "DELETE", "id": 3}, ...]\n'
    "Bei nichts Neuem: []"
)


class SoulMemory:
    """3-layer persistent memory backed by SQLite."""

    def __init__(self, db):
        self.db = db
        self._initialized = False
        self._tool_counter: Counter = Counter()

    async def init(self):
        if self._initialized:
            return
        self._initialized = True

    # ── CRUD ──────────────────────────────────────────────────

    async def add(
        self, layer: str, category: str, key: str, value: str,
        confidence: float = 0.8, source: str = "",
    ) -> int:
        cursor = await self.db._conn.execute(
            "INSERT INTO memories (layer, category, key, value, confidence, source, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (layer, category, key, value, confidence, source),
        )
        await self.db._conn.commit()
        return cursor.lastrowid

    async def update(self, memory_id: int, new_value: str = None, category: str = None, key: str = None):
        """Update an existing memory entry. Only updates provided fields."""
        fields = []
        params = []
        if new_value is not None:
            fields.append("value = ?")
            params.append(new_value)
        if category is not None:
            fields.append("category = ?")
            params.append(category)
        if key is not None:
            fields.append("key = ?")
            params.append(key)
        if not fields:
            return
        fields.append("updated_at = datetime('now')")
        params.append(memory_id)
        await self.db._conn.execute(
            f"UPDATE memories SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        await self.db._conn.commit()

    async def delete(self, memory_id: int):
        await self.db._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        await self.db._conn.commit()

    async def get_by_layer(self, layer: str) -> list[dict]:
        cursor = await self.db._conn.execute(
            "SELECT id, layer, category, key, value, confidence, source, created_at, updated_at "
            "FROM memories WHERE layer = ? ORDER BY updated_at DESC",
            (layer,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_all(self) -> list[dict]:
        cursor = await self.db._conn.execute(
            "SELECT id, layer, category, key, value, confidence, source "
            "FROM memories ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def find_similar(self, layer: str, value: str, threshold: float = 0.7) -> list[dict]:
        """Find memories with similar values using simple word-overlap matching."""
        all_memories = await self.get_by_layer(layer)
        similar = []
        value_lower = value.lower().strip()
        for mem in all_memories:
            mem_value = (mem.get('value') or '').lower().strip()
            if not value_lower or not mem_value:
                continue
            value_words = set(value_lower.split())
            mem_words = set(mem_value.split())
            if not value_words or not mem_words:
                continue
            overlap = len(value_words & mem_words) / max(len(value_words), len(mem_words))
            if overlap >= threshold:
                similar.append(mem)
        return similar

    async def upsert(self, layer: str, category: str, key: str, value: str) -> dict:
        """Insert or update memory. Updates the most similar existing entry if found."""
        similar = await self.find_similar(layer, value, threshold=0.6)
        if similar:
            existing = similar[0]
            existing_id = existing.get('id')
            await self.update(existing_id, new_value=value)
            return {"action": "updated", "id": existing_id}
        else:
            new_id = await self.add(layer, category, key, value, source="dashboard")
            return {"action": "created", "id": new_id}

    async def count(self) -> int:
        cursor = await self.db._conn.execute("SELECT COUNT(*) FROM memories")
        row = await cursor.fetchone()
        return row[0] if row else 0

    # ── Context block for prompt injection ────────────────────

    async def get_context_block(self, max_per_layer: int = 10) -> str:
        parts = []
        for layer, title in [
            ("user", "Was ich ueber dich weiss"),
            ("self", "Meine eigene Einschaetzung"),
            ("relationship", "Unsere Beziehung"),
        ]:
            mems = await self.get_by_layer(layer)
            if not mems:
                continue
            lines = [f"## {title}"]
            for m in mems[:max_per_layer]:
                lines.append(f"- {m['value']}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts)

    # ── Activity logging & daily profile ─────────────────────

    async def log_activity(self, chat_id: str):
        now = datetime.datetime.now()
        day_type = "weekend" if now.weekday() >= 5 else "weekday"
        await self.db._conn.execute(
            "INSERT INTO activity_log (chat_id, timestamp, day_type) VALUES (?, ?, ?)",
            (chat_id, now.isoformat(), day_type),
        )
        await self.db._conn.commit()

    async def compute_daily_profile(self, chat_id: str) -> dict:
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=14)).isoformat()
        cursor = await self.db._conn.execute(
            "SELECT timestamp, day_type FROM activity_log "
            "WHERE chat_id = ? AND timestamp > ? ORDER BY timestamp",
            (chat_id, cutoff),
        )
        rows = await cursor.fetchall()
        if not rows:
            return {
                "wake_up": "07:30", "peak_hours": "10:00-13:00",
                "lunch_break": "13:00-14:00", "evening_active": "20:00-23:30",
                "sleep": "00:00", "weekend_shift_hours": 1.5,
            }
        hours_weekday: list[int] = []
        hours_weekend: list[int] = []
        for row in rows:
            ts = datetime.datetime.fromisoformat(row["timestamp"])
            if row["day_type"] == "weekend":
                hours_weekend.append(ts.hour)
            else:
                hours_weekday.append(ts.hour)

        def _earliest(hours: list[int]) -> str:
            if not hours:
                return "07:30"
            return f"{min(hours):02d}:30"

        def _peak(hours: list[int]) -> str:
            if not hours:
                return "10:00-13:00"
            c = Counter(hours)
            top = c.most_common(3)
            start = min(h for h, _ in top)
            end = max(h for h, _ in top) + 1
            return f"{start:02d}:00-{end:02d}:00"

        wake = _earliest(hours_weekday or hours_weekend)
        peak = _peak(hours_weekday or hours_weekend)
        return {
            "wake_up": wake, "peak_hours": peak,
            "lunch_break": "13:00-14:00", "evening_active": "20:00-23:30",
            "sleep": "00:00", "weekend_shift_hours": 1.5,
        }

    # ── Tool usage tracking ──────────────────────────────────

    async def track_tool_usage(self, tool_name: str):
        self._tool_counter[tool_name] += 1

    async def get_tool_stats(self) -> dict[str, int]:
        return dict(self._tool_counter)

    # ── Memory extraction from conversation ──────────────────

    async def extract_memories(self, llm, user_message: str, assistant_response: str):
        try:
            existing = await self.get_all()
            existing_str = "\n".join(
                f"[{m['id']}] ({m['layer']}/{m['category']}) {m['key']}: {m['value']}"
                for m in existing[:30]
            )
            prompt = (
                f"Bestehende Fakten:\n{existing_str or '(keine)'}\n\n"
                f"Nutzer: {user_message[:1000]}\n"
                f"Assistent: {assistant_response[:1000]}\n\n"
                f"Welche neuen Fakten ergeben sich?"
            )
            response = await llm.chat(
                system_prompt=_EXTRACT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            text = response.strip()
            if "[" in text:
                text = text[text.index("["):text.rindex("]") + 1]
            actions = json.loads(text)
            if not isinstance(actions, list):
                return
            for action in actions:
                act = action.get("action", "").upper()
                if act == "ADD":
                    # Use upsert to avoid duplicates from repeated conversations
                    layer = action.get("layer", "user")
                    value = action.get("value", "")
                    if value:
                        similar = await self.find_similar(layer, value, threshold=0.6)
                        if similar:
                            await self.update(similar[0]['id'], new_value=value)
                        else:
                            await self.add(
                                layer=layer,
                                category=action.get("category", "general"),
                                key=action.get("key", ""),
                                value=value,
                                source="conversation",
                            )
                elif act == "UPDATE":
                    mid = action.get("id")
                    value = action.get("value", "")
                    if mid and value:
                        await self.update(int(mid), new_value=value)
                elif act == "DELETE":
                    mid = action.get("id")
                    if mid:
                        await self.delete(int(mid))
        except (json.JSONDecodeError, ValueError, KeyError):
            pass
        except Exception:
            pass

    # ── Migration helper ─────────────────────────────────────

    async def migrate_from_facts(self, fact_memory) -> int:
        facts = await fact_memory.get_all_active()
        count = 0
        for f in facts:
            await self.add(
                layer="user",
                category=f.category,
                key=f.content[:50].replace(" ", "_").lower(),
                value=f.content,
                source=f.source or "migrated",
            )
            count += 1
        return count
