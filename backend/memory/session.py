import time


class SessionMemory:
    """Per-agent RAM session buffer with max messages and inactivity timeout."""

    def __init__(self, max_messages: int = 15, timeout_seconds: int = 1800):
        self.max_messages = max_messages
        self.timeout = timeout_seconds
        self._buffers: dict[str, list[dict]] = {}
        self._last_active: dict[str, float] = {}

    def _check_timeout(self, agent_id: str):
        last = self._last_active.get(agent_id, 0)
        if time.time() - last > self.timeout:
            self._buffers.pop(agent_id, None)

    def get(self, agent_id: str) -> list[dict]:
        self._check_timeout(agent_id)
        return self._buffers.get(agent_id, [])

    def add(self, agent_id: str, message: dict):
        self._check_timeout(agent_id)
        if agent_id not in self._buffers:
            self._buffers[agent_id] = []
        self._buffers[agent_id].append(message)
        # Trim to max
        if len(self._buffers[agent_id]) > self.max_messages * 2:
            self._buffers[agent_id] = self._buffers[agent_id][-self.max_messages * 2:]
        self._last_active[agent_id] = time.time()

    def clear(self, agent_id: str):
        self._buffers.pop(agent_id, None)
        self._last_active.pop(agent_id, None)

    def touch(self, agent_id: str):
        """Reset timeout without adding a message."""
        self._last_active[agent_id] = time.time()

    def active_agents(self) -> list[str]:
        """Return agent IDs with active sessions."""
        now = time.time()
        return [
            aid for aid, last in self._last_active.items()
            if now - last <= self.timeout and aid in self._buffers
        ]
