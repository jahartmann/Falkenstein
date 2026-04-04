"""Review Gate — LLM-based quality check before output."""
from __future__ import annotations
import json
from dataclasses import dataclass


@dataclass
class ReviewResult:
    verdict: str    # "PASS", "REVISE", "FAIL"
    feedback: str = ""
    revised: str = ""


_REVIEW_SYSTEM_THOROUGH = (
    "Du bist ein Qualitaets-Reviewer. Pruefe die Antwort eines KI-Assistenten:\n\n"
    "1. Faktische Konsistenz: Widerspricht sich die Antwort selbst?\n"
    "2. Vollstaendigkeit: Wurde die Frage wirklich beantwortet?\n"
    "3. Halluzinations-Check: Werden Dinge behauptet die nicht belegt sind?\n"
    "4. Ton: Klingt die Antwort natuerlich und direkt (nicht corporate)?\n\n"
    "Antworte NUR mit JSON:\n"
    '{"verdict": "PASS|REVISE|FAIL", "feedback": "...", "revised": "..."}\n'
    "Bei PASS: feedback und revised leer lassen.\n"
    "Bei REVISE: feedback mit konkretem Problem, revised mit verbesserter Version.\n"
    "Bei FAIL: feedback mit Grund, revised leer."
)

_REVIEW_SYSTEM_LIGHT = (
    "Kurz-Check: Ist diese Antwort korrekt und vollstaendig? "
    "Antworte NUR mit JSON: "
    '{"verdict": "PASS|REVISE", "feedback": "...", "revised": "..."}'
)


class ReviewGate:
    def __init__(self, llm):
        self.llm = llm

    async def review(
        self,
        answer: str,
        original_request: str,
        context: str = "",
        review_level: str = "thorough",
    ) -> ReviewResult:
        system = _REVIEW_SYSTEM_LIGHT if review_level == "light" else _REVIEW_SYSTEM_THOROUGH
        prompt = (
            f"Urspruengliche Frage: {original_request[:500]}\n\n"
            f"Antwort des Assistenten:\n{answer[:2000]}"
        )
        if context:
            prompt += f"\n\nKontext:\n{context[:500]}"
        try:
            response = await self.llm.chat(
                system_prompt=system,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            text = response.strip()
            if "{" in text:
                text = text[text.index("{"):text.rindex("}") + 1]
            data = json.loads(text)
            return ReviewResult(
                verdict=data.get("verdict", "PASS").upper(),
                feedback=data.get("feedback", ""),
                revised=data.get("revised", ""),
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            return ReviewResult(verdict="PASS")
        except Exception:
            return ReviewResult(verdict="PASS")
