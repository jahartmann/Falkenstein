"""
LLMRouter — picks the right LLM backend per task type.
Supports: local (Ollama), claude (CLI), gemini (CLI).
Configurable per task type: classify, action, content, scheduled.
"""

from backend.llm_client import LLMClient
from backend.cli_llm_client import CLILLMClient

# Valid provider names
PROVIDERS = ("local", "claude", "gemini")

# Default routing: which provider for which task type
DEFAULT_ROUTING = {
    "classify": "local",
    "telegram": "local",
    "action": "local",
    "content": "local",
    "scheduled": "local",
}

# Size map: which task types use light vs heavy model
_SIZE_MAP: dict[str, str] = {
    "classify": "light",
    "telegram": "light",
    "action": "heavy",
    "content": "heavy",
    "scheduled": "heavy",
}


class LLMRouter:
    """Routes LLM calls to the right backend based on task type."""

    def __init__(self, local_llm: LLMClient, config_service=None):
        self.local = local_llm
        self._claude = CLILLMClient(provider="claude")
        self._gemini = CLILLMClient(provider="gemini")
        self._config_service = config_service
        # Routing config — load from config or use defaults
        self.routing: dict[str, str] = dict(DEFAULT_ROUTING)
        if config_service:
            for task_type in DEFAULT_ROUTING:
                key = f"llm_provider_{task_type}"
                saved = config_service.get(key)
                if saved and saved in PROVIDERS:
                    self.routing[task_type] = saved

    def get_client(self, task_type: str = "classify"):
        """Get the LLM client for a given task type."""
        provider = self.routing.get(task_type, "local")
        if provider == "claude":
            return self._claude
        elif provider == "gemini":
            return self._gemini
        return self.local

    def get_client_with_size(self, task_type: str = "classify") -> tuple:
        """Return (client, size) where size is 'light' or 'heavy'."""
        client = self.get_client(task_type)
        size = _SIZE_MAP.get(task_type, "heavy")
        return client, size

    async def set_routing(self, task_type: str, provider: str):
        """Update routing for a task type and persist."""
        if task_type in self.routing and provider in PROVIDERS:
            self.routing[task_type] = provider
            if self._config_service:
                await self._config_service.set(f"llm_provider_{task_type}", provider)

    def get_routing(self) -> dict[str, str]:
        """Get current routing config."""
        return dict(self.routing)
