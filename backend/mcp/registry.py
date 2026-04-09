"""MCP server registry — catalog-seeded, DB-persisted runtime state."""
from __future__ import annotations
import json
from datetime import datetime
from backend.mcp.catalog import CATALOG
from backend.mcp.config import MCPServerConfig, ServerStatus
from backend.mcp import installer


class MCPRegistry:
    """In-memory view of catalog + DB state. load_from_db populates."""

    def __init__(self) -> None:
        self._servers: dict[str, ServerStatus] = {}
        self._user_configs: dict[str, dict] = {}
        self._installed: dict[str, bool] = {}

    # ── loading ──────────────────────────────────────────────────────

    async def load_from_db(self, db) -> None:
        """Build registry from catalog + DB overrides."""
        self._servers.clear()
        self._user_configs.clear()
        self._installed.clear()

        # Read DB state for installed/enabled flags
        rows = {}
        async with db._conn.execute(
            "SELECT id, installed, enabled, config_json FROM mcp_servers"
        ) as cur:
            async for row in cur:
                rows[row[0]] = {
                    "installed": bool(row[1]),
                    "enabled": bool(row[2]),
                    "config_json": row[3],
                }

        # Seed one entry per catalog server
        for sid, entry in CATALOG.items():
            db_row = rows.get(sid, {})
            enabled = db_row.get("enabled", False)
            installed = db_row.get("installed", False)
            user_cfg = {}
            if db_row.get("config_json"):
                try:
                    user_cfg = json.loads(db_row["config_json"])
                except Exception:
                    user_cfg = {}
            # Resolved binary if installed, else placeholder
            bin_path = installer.resolve_binary(sid, entry["bin"])
            command = str(bin_path) if bin_path else "<not-installed>"
            config = MCPServerConfig(
                id=sid, name=entry["name"],
                command=command, args=[],
                env={},  # merged at start time
                enabled=enabled,
            )
            self._servers[sid] = ServerStatus(config=config)
            self._user_configs[sid] = user_cfg
            self._installed[sid] = installed

    # ── state queries ───────────────────────────────────────────────

    def catalog_entry(self, server_id: str) -> dict | None:
        return CATALOG.get(server_id)

    def get(self, server_id: str) -> ServerStatus | None:
        return self._servers.get(server_id)

    def list_servers(self) -> list[ServerStatus]:
        return list(self._servers.values())

    def list_enabled(self) -> list[ServerStatus]:
        return [s for s in self._servers.values() if s.config.enabled]

    def list_installed(self) -> list[ServerStatus]:
        return [s for s in self._servers.values() if self._installed.get(s.config.id)]

    def is_installed(self, server_id: str) -> bool:
        return self._installed.get(server_id, False)

    def get_user_config(self, server_id: str) -> dict:
        return dict(self._user_configs.get(server_id, {}))

    def update_status(
        self, server_id: str, *, status=None, pid=None,
        tools_count=None, last_error=None, uptime_seconds=None,
    ) -> None:
        s = self._servers.get(server_id)
        if s is None:
            return
        if status is not None: s.status = status
        if pid is not None: s.pid = pid
        if tools_count is not None: s.tools_count = tools_count
        if last_error is not None: s.last_error = last_error
        if uptime_seconds is not None: s.uptime_seconds = uptime_seconds

    # ── mutations (persisted) ───────────────────────────────────────

    async def set_installed(
        self, db, server_id: str, installed: bool,
        config: dict | None = None,
    ) -> None:
        self._installed[server_id] = installed
        if config is not None:
            self._user_configs[server_id] = dict(config)
        cfg_json = json.dumps(self._user_configs.get(server_id, {}))
        now = datetime.utcnow().isoformat()
        await db._conn.execute(
            """INSERT INTO mcp_servers (id, installed, enabled, config_json, installed_at, updated_at)
               VALUES (?, ?, COALESCE((SELECT enabled FROM mcp_servers WHERE id=?),0), ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   installed=excluded.installed,
                   config_json=excluded.config_json,
                   installed_at=excluded.installed_at,
                   updated_at=excluded.updated_at""",
            (server_id, int(installed), server_id, cfg_json, now, now),
        )
        await db._conn.commit()

    async def set_enabled(self, db, server_id: str, enabled: bool) -> None:
        s = self._servers.get(server_id)
        if s is not None:
            s.config.enabled = enabled
        now = datetime.utcnow().isoformat()
        await db._conn.execute(
            """INSERT INTO mcp_servers (id, installed, enabled, updated_at)
               VALUES (?, COALESCE((SELECT installed FROM mcp_servers WHERE id=?),0), ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   enabled=excluded.enabled,
                   updated_at=excluded.updated_at""",
            (server_id, server_id, int(enabled), now),
        )
        await db._conn.commit()

    async def set_last_error(self, db, server_id: str, err: str | None) -> None:
        s = self._servers.get(server_id)
        if s is not None:
            s.last_error = err
        await db._conn.execute(
            "UPDATE mcp_servers SET last_error=?, updated_at=? WHERE id=?",
            (err, datetime.utcnow().isoformat(), server_id),
        )
        await db._conn.commit()

    # ── migration ───────────────────────────────────────────────────

    async def migrate_from_env(self, db, legacy_flags: dict) -> None:
        """One-shot migration of old .env MCP flags into DB.
        Idempotent — running multiple times does no harm."""
        mapping = {
            "mcp_apple_enabled": "apple-mcp",
            "mcp_desktop_commander_enabled": "desktop-commander",
            "mcp_obsidian_enabled": "mcp-obsidian",
        }
        now = datetime.utcnow().isoformat()
        for flag_key, server_id in mapping.items():
            if server_id not in CATALOG:
                continue
            enabled = bool(legacy_flags.get(flag_key, False))
            if not enabled:
                continue
            await db._conn.execute(
                """INSERT INTO mcp_servers (id, installed, enabled, updated_at)
                   VALUES (?, 0, 1, ?)
                   ON CONFLICT(id) DO NOTHING""",
                (server_id, now),
            )
        await db._conn.commit()

    # ── deprecated shims (will be removed in Task 16) ───────────────

    @classmethod
    def from_settings(cls, **kwargs) -> "MCPRegistry":
        """Deprecated — will be removed in Task 16. Returns empty registry."""
        return cls()
