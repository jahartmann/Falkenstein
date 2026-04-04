"""Self-Evolution — weekly reflection and SOUL.md growth proposals."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from pathlib import Path


_SOUL_PATH = Path(__file__).parent.parent.parent / "SOUL.md"

_REFLECT_SYSTEM = (
    "Du bist Falki und reflektierst deine Woche. Analysiere deine Erfahrungen "
    "und schlage Persoenlichkeits-Updates vor.\n\n"
    "Input: Deine Self-Memory-Eintraege + Tool-Nutzungsstatistiken.\n"
    "Output: JSON-Array mit Vorschlaegen (max 1 pro Woche):\n"
    '[{"observation": "Ich habe gemerkt dass...", "proposal": "Soll ich X aufnehmen?", '
    '"soul_addition": "- Konkreter Text fuer SOUL.md", "category": "communication|approach|expertise"}]\n'
    "Bei keinen Vorschlaegen: []"
)


@dataclass
class EvolutionProposal:
    observation: str
    proposal: str
    soul_addition: str
    category: str


class SelfEvolution:
    def __init__(self, llm, soul_memory):
        self.llm = llm
        self.soul_memory = soul_memory

    async def weekly_reflection(self) -> list[EvolutionProposal]:
        self_mems = await self.soul_memory.get_by_layer("self")
        tool_stats = await self.soul_memory.get_tool_stats()
        mems_str = "\n".join(
            f"- [{m['category']}] {m['value']}" for m in self_mems[:20]
        )
        tools_str = "\n".join(
            f"- {name}: {count}x genutzt" for name, count in
            sorted(tool_stats.items(), key=lambda x: x[1], reverse=True)[:10]
        )
        prompt = (
            f"Meine Erfahrungen diese Woche:\n{mems_str or '(keine)'}\n\n"
            f"Tool-Nutzung:\n{tools_str or '(keine)'}\n\n"
            f"Welche Persoenlichkeits-Updates schlage ich vor?"
        )
        try:
            response = await self.llm.chat(
                system_prompt=_REFLECT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            text = response.strip()
            if "[" in text:
                text = text[text.index("["):text.rindex("]") + 1]
            items = json.loads(text)
            if not isinstance(items, list):
                return []
            return [
                EvolutionProposal(
                    observation=item.get("observation", ""),
                    proposal=item.get("proposal", ""),
                    soul_addition=item.get("soul_addition", ""),
                    category=item.get("category", ""),
                )
                for item in items[:1]
            ]
        except (json.JSONDecodeError, ValueError):
            return []
        except Exception:
            return []

    def is_immutable_section(self, text: str, soul_content: str) -> bool:
        immutable_blocks = re.findall(
            r"<!-- IMMUTABLE -->(.*?)<!-- /IMMUTABLE -->",
            soul_content, re.DOTALL,
        )
        for block in immutable_blocks:
            if text.strip() in block:
                return True
        return False

    def apply_proposal(self, soul_content: str, proposal: EvolutionProposal) -> str:
        if self.is_immutable_section(proposal.soul_addition, soul_content):
            return soul_content
        section_map = {
            "harte regeln": "## Harte Regeln",
        }
        # Refuse if the target heading resolves to an immutable section
        if proposal.category.lower() in section_map:
            target = section_map[proposal.category.lower()]
            if self.is_immutable_section(target, soul_content):
                return soul_content
        section_map = {
            "communication": "## Kommunikation",
            "approach": "## Wie ich arbeite",
            "expertise": "## Wie ich arbeite",
            "charakter": "## Charakter",
        }
        target_heading = section_map.get(proposal.category.lower(), "## Wie ich arbeite")
        if target_heading in soul_content:
            idx = soul_content.index(target_heading)
            section_end = soul_content.find("\n## ", idx + len(target_heading))
            if section_end == -1:
                return soul_content.rstrip() + "\n" + proposal.soul_addition + "\n"
            else:
                return (
                    soul_content[:section_end].rstrip() + "\n"
                    + proposal.soul_addition + "\n"
                    + soul_content[section_end:]
                )
        else:
            return soul_content.rstrip() + f"\n\n{target_heading}\n{proposal.soul_addition}\n"

    async def propose_and_notify(self, telegram=None, chat_id: str = "") -> list[EvolutionProposal]:
        proposals = await self.weekly_reflection()
        if proposals and telegram:
            for p in proposals:
                msg = (
                    f"🧠 *Self-Reflection:*\n\n"
                    f"{p.observation}\n\n"
                    f"Vorschlag: {p.proposal}\n\n"
                    f"Aenderung: `{p.soul_addition}`"
                )
                if hasattr(telegram, "send_message_with_buttons"):
                    await telegram.send_message_with_buttons(
                        msg,
                        [[
                            {"text": "✅ Ja, aufnehmen", "callback_data": f"soul_accept_{p.category}"},
                            {"text": "❌ Nein", "callback_data": "soul_reject"},
                        ]],
                        chat_id=chat_id or None,
                    )
                else:
                    await telegram.send_message(msg, chat_id=chat_id or None)
        return proposals
