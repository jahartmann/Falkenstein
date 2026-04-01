from enum import Enum
from backend.models import AgentTraits, AgentMood


class PersonalityEvent(str, Enum):
    TASK_SUCCESS = "task_success"
    TASK_FAILURE = "task_failure"
    CLI_ESCALATION = "cli_escalation"
    SUCCESSFUL_COLLAB = "successful_collab"
    REVIEW_NEGATIVE = "review_negative"
    REVIEW_POSITIVE = "review_positive"
    RECEIVED_PRAISE = "received_praise"
    IDLE_CHAT = "idle_chat"
    SOLO_BUG_FIX = "solo_bug_fix"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


EVENT_EFFECTS: dict[PersonalityEvent, dict] = {
    PersonalityEvent.TASK_SUCCESS: {
        "traits": {"confidence": 0.03},
        "mood": {"stress": -0.1, "motivation": 0.05},
    },
    PersonalityEvent.TASK_FAILURE: {
        "traits": {"patience": -0.02},
        "mood": {"frustration": 0.15, "stress": 0.1, "motivation": -0.05},
    },
    PersonalityEvent.CLI_ESCALATION: {
        "traits": {"confidence": -0.02},
        "mood": {"stress": 0.05},
    },
    PersonalityEvent.SUCCESSFUL_COLLAB: {
        "traits": {"social": 0.01},
        "mood": {"motivation": 0.1, "energy": 0.05},
    },
    PersonalityEvent.REVIEW_NEGATIVE: {
        "traits": {"patience": -0.01},
        "mood": {"frustration": 0.1, "stress": 0.05},
    },
    PersonalityEvent.REVIEW_POSITIVE: {
        "traits": {"confidence": 0.02},
        "mood": {"motivation": 0.05},
    },
    PersonalityEvent.RECEIVED_PRAISE: {
        "traits": {"leadership": 0.02, "confidence": 0.02},
        "mood": {"motivation": 0.15, "stress": -0.05},
    },
    PersonalityEvent.IDLE_CHAT: {
        "traits": {},
        "mood": {"energy": 0.02},
    },
    PersonalityEvent.SOLO_BUG_FIX: {
        "traits": {"confidence": 0.05, "focus": 0.01},
        "mood": {"motivation": 0.1},
    },
}

MOOD_BASELINE = {"energy": 0.7, "stress": 0.15, "motivation": 0.6, "frustration": 0.0}
MOOD_DECAY_RATE = 0.05


class PersonalityEngine:
    def apply_event(self, traits: AgentTraits, mood: AgentMood, event: PersonalityEvent) -> tuple[AgentTraits, AgentMood]:
        effects = EVENT_EFFECTS.get(event, {"traits": {}, "mood": {}})

        trait_dict = traits.model_dump()
        for key, delta in effects.get("traits", {}).items():
            if key in trait_dict:
                trait_dict[key] = _clamp(trait_dict[key] + delta)
        new_traits = AgentTraits(**trait_dict)

        mood_dict = mood.model_dump()
        for key, delta in effects.get("mood", {}).items():
            if key in mood_dict:
                mood_dict[key] = _clamp(mood_dict[key] + delta)
        new_mood = AgentMood(**mood_dict)

        return new_traits, new_mood

    def decay_mood(self, mood: AgentMood) -> AgentMood:
        mood_dict = mood.model_dump()
        for key, baseline in MOOD_BASELINE.items():
            current = mood_dict[key]
            diff = baseline - current
            mood_dict[key] = _clamp(current + diff * MOOD_DECAY_RATE)
        return AgentMood(**mood_dict)
