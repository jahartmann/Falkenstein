"""Intent Engine — NL parsing to structured intents + prompt enrichment."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime


_INTENT_SYSTEM = (
    "Du bist ein Intent-Parser fuer einen KI-Assistenten namens Falki.\n"
    "Analysiere die Nachricht des Nutzers und bestimme:\n\n"
    "1. type: quick | content | action | reminder | schedule | planned_task | multi_step\n"
    "2. enriched_prompt: Optimierter, detaillierter Prompt (aus 10 Worten mach 200)\n"
    "3. confidence: 0.0-1.0 wie sicher du dir bist\n"
    "4. time_expr: Erkannte Zeitausdruecke (als ISO datetime wenn moeglich)\n"
    "5. needs_clarification: true wenn zu vage\n"
    "6. clarification_question: Rueckfrage wenn noetig\n"
    "7. steps: Bei planned_task/multi_step — Array von {prompt, scheduled_at}\n\n"
    "Zeitausdruecke aufloesen:\n"
    "- 'morgen frueh' → nutze wake_up aus daily_profile\n"
    "- 'heute abend' → 20:00 (oder evening_active aus Profil)\n"
    "- 'wenn ich Zeit hab' → peak_hours Luecke\n\n"
    "Antworte NUR mit JSON."
)


@dataclass
class ParsedIntent:
    type: str
    enriched_prompt: str = ""
    confidence: float = 0.5
    time_expressions: list[str] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    steps: list[dict] | None = None


class IntentEngine:
    def __init__(self, llm):
        self.llm = llm

    async def parse(
        self,
        text: str,
        current_time: datetime | None = None,
        daily_profile: dict | None = None,
        user_memory_context: str = "",
    ) -> ParsedIntent:
        now = current_time or datetime.now()
        profile_str = ""
        if daily_profile:
            profile_str = f"\nDaily Profile: {json.dumps(daily_profile)}"
        context = f"Aktuelle Zeit: {now.isoformat()}{profile_str}"
        if user_memory_context:
            context += f"\nBekannte Nutzer-Infos:\n{user_memory_context}"
        prompt = f"{context}\n\nNachricht: {text}"
        try:
            response = await self.llm.chat(
                system_prompt=_INTENT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            raw = response.strip()
            if "{" in raw:
                raw = raw[raw.index("{"):raw.rindex("}") + 1]
            data = json.loads(raw)
            return ParsedIntent(
                type=data.get("type", "passthrough"),
                enriched_prompt=data.get("enriched_prompt", text),
                confidence=float(data.get("confidence", 0.5)),
                time_expressions=[data["time_expr"]] if data.get("time_expr") else [],
                needs_clarification=bool(data.get("needs_clarification", False)),
                clarification_question=data.get("clarification_question"),
                steps=data.get("steps"),
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            return ParsedIntent(type="passthrough", enriched_prompt=text, confidence=0.0)
        except Exception:
            return ParsedIntent(type="passthrough", enriched_prompt=text, confidence=0.0)
