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
    "action": "local",
    "content": "local",
    "scheduled": "local",
}


class LLMRouter:
    """Routes LLM calls to the right backend based on task type."""

    def __init__(self, local_llm: LLMClient):
        self.local = local_llm
        self._claude = CLILLMClient(provider="claude")
        self._gemini = CLILLMClient(provider="gemini")
        # Routing config — can be changed at runtime
        self.routing: dict[str, str] = dict(DEFAULT_ROUTING)

    def get_client(self, task_type: str = "classify"):
        """Get the LLM client for a given task type."""
        provider = self.routing.get(task_type, "local")
        if provider == "claude":
            return self._claude
        elif provider == "gemini":
            return self._gemini
        return self.local

    def set_routing(self, task_type: str, provider: str):
        """Update routing for a task type."""
        if task_type in self.routing and provider in PROVIDERS:
            self.routing[task_type] = provider

    def get_routing(self) -> dict[str, str]:
        """Get current routing config."""
        return dict(self.routing)
