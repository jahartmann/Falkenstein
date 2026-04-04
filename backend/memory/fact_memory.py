"""
Fact Memory — persistent user/project facts extracted from conversations.
Mem0-style: after each exchange, extract facts via LLM, then ADD/UPDATE/DELETE.
Storage: SQLite (same DB as tasks). Retrieval: keyword + recency scoring.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field


@dataclass
class Fact:
    id: int = 0
    category: str = ""        # user, project, preference, tool, knowledge
    content: str = ""
    source: str = ""          # which conversation/context produced this
    created_at: float = 0.0
    updated_at: float = 0.0
    active: bool = True       # soft-delete instead of hard-delete


# SQL for the facts table
FACTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL DEFAULT 'general',
    content TEXT NOT NULL,
    source TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
)
"""


class FactMemory:
    """Persistent fact store backed by aiosqlite."""

    def __init__(self, db):
        self.db = db  # Database instance (backend.database.Database)
        self._initialized = False

    async def init(self):
        """Create facts table if needed."""
        if self._initialized:
            return
        await self.db._conn.execute(FACTS_TABLE_SQL)
        await self.db._conn.commit()
        self._initialized = True

    async def get_all_active(self) -> list[Fact]:
        """Get all active facts."""
        await self.init()
        cursor = await self.db._conn.execute(
            "SELECT id, category, content, source, created_at, updated_at, active "
            "FROM facts WHERE active = 1 ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        return [Fact(id=r[0], category=r[1], content=r[2], source=r[3],
                     created_at=r[4], updated_at=r[5], active=bool(r[6]))
                for r in rows]

    async def add(self, category: str, content: str, source: str = "") -> int:
        """Add a new fact. Returns the fact ID."""
        await self.init()
        now = time.time()
        cursor = await self.db._conn.execute(
            "INSERT INTO facts (category, content, source, created_at, updated_at, active) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (category, content, source, now, now),
        )
        await self.db._conn.commit()
        return cursor.lastrowid

    async def update(self, fact_id: int, new_content: str):
        """Update an existing fact's content."""
        now = time.time()
        await self.db._conn.execute(
            "UPDATE facts SET content = ?, updated_at = ? WHERE id = ?",
            (new_content, now, fact_id),
        )
        await self.db._conn.commit()

    async def deactivate(self, fact_id: int):
        """Soft-delete a fact."""
        now = time.time()
        await self.db._conn.execute(
            "UPDATE facts SET active = 0, updated_at = ? WHERE id = ?",
            (now, fact_id),
        )
        await self.db._conn.commit()

    async def search(self, query: str, limit: int = 10) -> list[Fact]:
        """Simple keyword search over active facts."""
        await self.init()
        cursor = await self.db._conn.execute(
            "SELECT id, category, content, source, created_at, updated_at, active "
            "FROM facts WHERE active = 1 AND content LIKE ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (f"%{query}%", limit),
        )
        rows = await cursor.fetchall()
        return [Fact(id=r[0], category=r[1], content=r[2], source=r[3],
                     created_at=r[4], updated_at=r[5], active=bool(r[6]))
                for r in rows]

    async def get_context_block(self, max_facts: int = 20) -> str:
        """Build a context string of all active facts for injection into system prompt."""
        facts = await self.get_all_active()
        if not facts:
            return ""
        # Group by category
        grouped: dict[str, list[str]] = {}
        for f in facts[:max_facts]:
            grouped.setdefault(f.category, []).append(f.content)
        lines = ["## Mein Wissen (Fakten aus bisherigen Gesprächen)"]
        for cat, items in grouped.items():
            lines.append(f"\n### {cat.title()}")
            for item in items:
                lines.append(f"- {item}")
        return "\n".join(lines)

    async def count(self) -> int:
        await self.init()
        cursor = await self.db._conn.execute("SELECT COUNT(*) FROM facts WHERE active = 1")
        row = await cursor.fetchone()
        return row[0] if row else 0


# ── Extraction prompt — runs async after each exchange ──────

_EXTRACT_SYSTEM = (
    "Du analysierst ein Gespräch und extrahierst neue Fakten über den Nutzer oder das Projekt.\n"
    "Vergleiche mit den bestehenden Fakten und entscheide für jeden neuen Fakt:\n"
    "- ADD: Neuer Fakt, noch nicht bekannt\n"
    "- UPDATE: Bestehender Fakt muss aktualisiert werden (gib die fact_id an)\n"
    "- DELETE: Bestehender Fakt ist veraltet/falsch (gib die fact_id an)\n"
    "- NOOP: Nichts zu tun\n\n"
    "Kategorien: user, project, preference, tool, knowledge\n\n"
    "Antworte NUR mit JSON-Array:\n"
    '[{"action": "ADD", "category": "user", "content": "..."}, ...]\n'
    '[{"action": "UPDATE", "fact_id": 5, "content": "neuer Inhalt"}, ...]\n'
    '[{"action": "DELETE", "fact_id": 3}, ...]\n'
    "Bei NOOP: leeres Array []"
)


async def extract_and_store_facts(
    llm, fact_memory: FactMemory, user_message: str, assistant_response: str
):
    """Run fact extraction asynchronously after an exchange. Fire-and-forget."""
    try:
        existing_facts = await fact_memory.get_all_active()
        facts_str = "\n".join(
            f"[{f.id}] ({f.category}) {f.content}" for f in existing_facts[:30]
        )

        prompt = (
            f"Bestehende Fakten:\n{facts_str or '(keine)'}\n\n"
            f"Nutzer: {user_message[:1000]}\n"
            f"Assistent: {assistant_response[:1000]}\n\n"
            f"Welche neuen Fakten ergeben sich?"
        )

        response = await llm.chat(
            system_prompt=_EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )

        # Parse JSON from response
        text = response.strip()
        if "[" in text:
            text = text[text.index("["):text.rindex("]") + 1]
        actions = json.loads(text)

        if not isinstance(actions, list):
            return

        for action in actions:
            act = action.get("action", "").upper()
            if act == "ADD":
                await fact_memory.add(
                    category=action.get("category", "general"),
                    content=action.get("content", ""),
                    source="conversation",
                )
            elif act == "UPDATE":
                fid = action.get("fact_id")
                content = action.get("content", "")
                if fid and content:
                    await fact_memory.update(int(fid), content)
            elif act == "DELETE":
                fid = action.get("fact_id")
                if fid:
                    await fact_memory.deactivate(int(fid))

    except (json.JSONDecodeError, ValueError, KeyError):
        pass  # Extraction failed silently — not critical
    except Exception:
        pass  # Don't crash the main flow for memory extraction
