"""Dynamic agent identities — personality-driven agent selection."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml

_AGENTS_PATH = Path(__file__).parent / "agents.yaml"

_KEYWORD_MAP: dict[str, list[str]] = {
    "research": ["recherch", "such", "find", "info", "was gibt es", "neuigkeiten"],
    "coding": ["code", "script", "programm", "debug", "fix", "implementier", "schreib ein"],
    "writing": ["schreib", "text", "dokument", "guide", "artikel", "zusammenfass"],
    "sysadmin": ["install", "konfigurier", "server", "system", "service", "starte", "stoppe"],
    "data-analysis": ["analys", "daten", "statistik", "chart", "trend", "auswert"],
    "architecture": ["architektur", "design", "plan", "struktur", "refactor"],
    "devops": ["deploy", "pipeline", "docker", "ci", "cd", "automat"],
}

@dataclass
class AgentIdentity:
    name: str
    role: str
    personality: str
    approach: str = ""
    strengths: list[str] = field(default_factory=list)
    tool_priority: list[str] = field(default_factory=list)

    def build_system_prompt(self, soul_content: str = "", task_context: str = "") -> str:
        parts = []
        if soul_content:
            parts.append(soul_content)
        parts.append(
            f"## Dein Profil\n"
            f"Name: {self.name}\n"
            f"Rolle: {self.role}\n"
            f"Persoenlichkeit: {self.personality}\n"
        )
        if self.approach:
            parts.append(f"Herangehensweise: {self.approach}")
        if task_context:
            parts.append(f"\n## Aufgabe\n{task_context}")
        parts.append(
            "\nDu hast Zugriff auf alle verfuegbaren Tools. "
            "Nutze sie aktiv um die Aufgabe zu loesen. "
            "Antworte auf Deutsch."
        )
        return "\n\n".join(parts)


def load_agent_pool(path: Path | None = None) -> list[AgentIdentity]:
    p = path or _AGENTS_PATH
    if not p.exists():
        return [_fallback_agent()]
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    agents = []
    for entry in data.get("agents", []):
        agents.append(AgentIdentity(
            name=entry["name"],
            role=entry["role"],
            personality=entry.get("personality", ""),
            strengths=entry.get("strengths", []),
            tool_priority=entry.get("default_tools", []),
        ))
    return agents or [_fallback_agent()]


def select_agent(task_description: str, pool: list[AgentIdentity] | None = None) -> AgentIdentity:
    if pool is None:
        pool = load_agent_pool()
    task_lower = task_description.lower()
    scores: list[tuple[int, AgentIdentity]] = []
    for agent in pool:
        score = 0
        for strength in agent.strengths:
            keywords = _KEYWORD_MAP.get(strength, [])
            for kw in keywords:
                if kw in task_lower:
                    score += 1
        scores.append((score, agent))
    scores.sort(key=lambda x: x[0], reverse=True)
    if scores and scores[0][0] > 0:
        return scores[0][1]
    for agent in pool:
        if agent.name == "Kai":
            return agent
    return pool[0]


def _fallback_agent() -> AgentIdentity:
    return AgentIdentity(
        name="Kai", role="Allrounder",
        personality="Flexibel und loesungsorientiert.",
        strengths=["general"],
        tool_priority=["shell_runner", "web_research"],
    )
