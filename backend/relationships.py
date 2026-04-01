from enum import Enum
from backend.database import Database
from backend.models import RelationshipData

DUO_SYNERGY_THRESHOLD = 0.85


class RelationshipEvent(str, Enum):
    COLLAB_SUCCESS = "collab_success"
    COLLAB_FAILURE = "collab_failure"
    REVIEW_CLEAN = "review_clean"
    REVIEW_ISSUES = "review_issues"
    IDLE_CHAT = "idle_chat"
    HELPED_WITH_BUG = "helped_with_bug"


EVENT_DELTAS: dict[RelationshipEvent, dict[str, float]] = {
    RelationshipEvent.COLLAB_SUCCESS: {"synergy": 0.05, "trust": 0.03, "respect": 0.02},
    RelationshipEvent.COLLAB_FAILURE: {"synergy": -0.02, "trust": -0.01},
    RelationshipEvent.REVIEW_CLEAN: {"respect": 0.05, "trust": 0.02},
    RelationshipEvent.REVIEW_ISSUES: {"respect": -0.02},
    RelationshipEvent.IDLE_CHAT: {"friendship": 0.03},
    RelationshipEvent.HELPED_WITH_BUG: {"synergy": 0.03, "trust": 0.05, "friendship": 0.02},
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class RelationshipEngine:
    def __init__(self, db: Database):
        self.db = db

    async def record_event(self, agent_a: str, agent_b: str, event: RelationshipEvent):
        rel = await self.db.get_relationship(agent_a, agent_b)
        if rel is None:
            rel = RelationshipData(agent_a=agent_a, agent_b=agent_b)
        deltas = EVENT_DELTAS.get(event, {})
        rel_dict = rel.model_dump()
        for key, delta in deltas.items():
            if key in rel_dict and isinstance(rel_dict[key], float):
                rel_dict[key] = _clamp(rel_dict[key] + delta)
        updated = RelationshipData(**rel_dict)
        await self.db.upsert_relationship(updated)

    async def detect_duos(self) -> list[tuple[str, str]]:
        all_rels = await self.db.get_all_relationships()
        duos = []
        for rel in all_rels:
            if rel.synergy >= DUO_SYNERGY_THRESHOLD:
                duos.append((rel.agent_a, rel.agent_b))
        return duos

    async def get_best_partner(self, agent_id: str) -> str | None:
        rels = await self.db.get_relationships_for(agent_id)
        if not rels:
            return None
        best = max(rels, key=lambda r: r.synergy + r.friendship)
        return best.agent_b if best.agent_a == agent_id else best.agent_a
