"""MCP server registry — tracks config and runtime status."""
from __future__ import annotations
from backend.mcp.config import MCPServerConfig, ServerStatus

KNOWN_SERVERS: dict[str, dict] = {
    "apple-mcp": {"name": "Apple Services", "command": "npx", "args": ["-y", "apple-mcp"]},
    "desktop-commander": {"name": "Desktop Commander", "command": "npx", "args": ["-y", "@anthropic/desktop-commander"]},
    "mcp-obsidian": {"name": "Obsidian Vault", "command": "npx", "args": ["-y", "mcp-obsidian"]},
}


class MCPRegistry:
    def __init__(self) -> None:
        self._servers: dict[str, ServerStatus] = {}

    def register(self, config: MCPServerConfig) -> None:
        self._servers[config.id] = ServerStatus(config=config)

    def get(self, server_id: str) -> ServerStatus | None:
        return self._servers.get(server_id)

    def list_servers(self) -> list[ServerStatus]:
        return list(self._servers.values())

    def list_enabled(self) -> list[ServerStatus]:
        return [s for s in self._servers.values() if s.config.enabled]

    def toggle(self, server_id: str, enabled: bool) -> None:
        if server_id in self._servers:
            self._servers[server_id].config.enabled = enabled

    def update_status(
        self,
        server_id: str,
        *,
        status: str | None = None,
        pid: int | None = None,
        tools_count: int | None = None,
        last_error: str | None = None,
        uptime_seconds: float | None = None,
    ) -> None:
        s = self._servers.get(server_id)
        if s is None:
            return
        if status is not None:
            s.status = status
        if pid is not None:
            s.pid = pid
        if tools_count is not None:
            s.tools_count = tools_count
        if last_error is not None:
            s.last_error = last_error
        if uptime_seconds is not None:
            s.uptime_seconds = uptime_seconds

    @classmethod
    def from_settings(
        cls,
        server_ids: str,
        enabled_flags: dict[str, bool],
        node_path: str = "npx",
    ) -> MCPRegistry:
        reg = cls()
        for sid in server_ids.split(","):
            sid = sid.strip()
            if not sid:
                continue
            known = KNOWN_SERVERS.get(sid, {})
            config = MCPServerConfig(
                id=sid,
                name=known.get("name", sid),
                command=node_path,
                args=known.get("args", ["-y", sid]),
                enabled=enabled_flags.get(sid, True),
            )
            reg.register(config)
        return reg
