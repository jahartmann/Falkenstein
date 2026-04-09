"""MCP tool permission resolution: DB → catalog → heuristic → fail-safe."""
from __future__ import annotations
import re
from datetime import datetime
from backend.mcp.catalog import CATALOG

VALID_DECISIONS = {"allow", "ask", "deny"}

# Order matters: sensitive is checked first so send_get_info → ask
SENSITIVE_PATTERNS = [
    re.compile(r"^(create|delete|remove|update|set|write|send|post|put|patch)[_A-Z]", re.I),
    re.compile(r"^(execute|run|spawn|kill|stop|start|restart)[_A-Z]", re.I),
    re.compile(r"^(play|pause|skip|enable|disable|toggle)[_A-Z]", re.I),
    re.compile(r"_(execute|run|write|delete)$", re.I),
]

SAFE_PATTERNS = [
    re.compile(r"^(get|list|read|search|find|query|fetch|show|describe)[_A-Z]", re.I),
    re.compile(r"^(count|exists|has|is)[_A-Z]", re.I),
    re.compile(r"_(info|status|metadata|list|count)$", re.I),
]


def classify_heuristic(tool_name: str, description: str = "") -> str:
    """Return 'allow' | 'ask' based on patterns. Fail-safe default is 'ask'."""
    for p in SENSITIVE_PATTERNS:
        if p.search(tool_name):
            return "ask"
    for p in SAFE_PATTERNS:
        if p.search(tool_name):
            return "allow"
    return "ask"


class PermissionResolver:
    """Resolves effective permission for (server_id, tool_name)."""

    def __init__(self, db) -> None:
        self._db = db

    async def check(self, server_id: str, tool_name: str,
                    description: str = "") -> str:
        # 1. DB override
        async with self._db._conn.execute(
            "SELECT decision FROM mcp_tool_permissions WHERE server_id=? AND tool_name=?",
            (server_id, tool_name),
        ) as cur:
            row = await cur.fetchone()
            if row and row[0] in VALID_DECISIONS:
                return row[0]

        # 2. Catalog override
        entry = CATALOG.get(server_id, {})
        catalog_perms = entry.get("permissions", {})
        if tool_name in catalog_perms and catalog_perms[tool_name] in VALID_DECISIONS:
            return catalog_perms[tool_name]

        # 3. Heuristic
        return classify_heuristic(tool_name, description)

    async def set_override(self, server_id: str, tool_name: str, decision: str) -> None:
        if decision not in VALID_DECISIONS:
            raise ValueError(f"invalid decision: {decision}")
        now = datetime.utcnow().isoformat()
        await self._db._conn.execute(
            """INSERT INTO mcp_tool_permissions (server_id, tool_name, decision, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(server_id, tool_name) DO UPDATE SET
                   decision=excluded.decision, updated_at=excluded.updated_at""",
            (server_id, tool_name, decision, now),
        )
        await self._db._conn.commit()

    async def clear_override(self, server_id: str, tool_name: str) -> None:
        await self._db._conn.execute(
            "DELETE FROM mcp_tool_permissions WHERE server_id=? AND tool_name=?",
            (server_id, tool_name),
        )
        await self._db._conn.commit()

    async def list_overrides(self) -> list[dict]:
        rows = []
        async with self._db._conn.execute(
            "SELECT server_id, tool_name, decision FROM mcp_tool_permissions"
        ) as cur:
            async for r in cur:
                rows.append({"server_id": r[0], "tool_name": r[1], "decision": r[2]})
        return rows
