"""Static curated catalog of known MCP servers."""
from __future__ import annotations

REQUIRED_FIELDS = (
    "name", "description", "package", "bin",
    "category", "platform", "risk_level",
    "requires_config", "permissions",
)

VALID_RISK_LEVELS = {"low", "medium", "high"}


def validate_entry(server_id: str, entry: dict) -> None:
    for f in REQUIRED_FIELDS:
        if f not in entry:
            raise ValueError(f"catalog entry '{server_id}' missing field '{f}'")
    if entry["risk_level"] not in VALID_RISK_LEVELS:
        raise ValueError(
            f"catalog entry '{server_id}' has invalid risk_level "
            f"'{entry['risk_level']}'"
        )
    if not isinstance(entry["platform"], list):
        raise ValueError(f"catalog entry '{server_id}': platform must be list")
    if not isinstance(entry["requires_config"], list):
        raise ValueError(f"catalog entry '{server_id}': requires_config must be list")
    if not isinstance(entry["permissions"], dict):
        raise ValueError(f"catalog entry '{server_id}': permissions must be dict")


CATALOG: dict[str, dict] = {
    "apple-mcp": {
        "name": "Apple Services",
        "description": "Reminders, Calendar, Notes, Messages, Music, Maps (macOS only)",
        "package": "apple-mcp",
        "bin": "apple-mcp",
        "category": "productivity",
        "platform": ["darwin"],
        "risk_level": "medium",
        "requires_config": [],
        "permissions": {
            "get_reminders": "allow",
            "get_calendar_events": "allow",
            "get_notes": "allow",
            "play_music": "allow",
            "pause_music": "allow",
            "send_message": "ask",
            "create_reminder": "ask",
            "create_note": "ask",
        },
    },
    "mcp-obsidian": {
        "name": "Obsidian Vault",
        "description": "Read and write notes in an Obsidian vault",
        "package": "mcp-obsidian",
        "bin": "mcp-obsidian",
        "category": "knowledge",
        "platform": [],
        "risk_level": "medium",
        "requires_config": ["vault_path"],
        "permissions": {},
    },
    "desktop-commander": {
        "name": "Desktop Commander",
        "description": "Shell, file operations, process management",
        "package": "@wonderwhy-er/desktop-commander",
        "bin": "desktop-commander",
        "category": "system",
        "platform": [],
        "risk_level": "high",
        "requires_config": [],
        "permissions": {},
    },
    "filesystem": {
        "name": "Filesystem",
        "description": "Read, write, and search files in allowed directories",
        "package": "@modelcontextprotocol/server-filesystem",
        "bin": "mcp-server-filesystem",
        "category": "system",
        "platform": [],
        "risk_level": "high",
        "requires_config": ["allowed_directories"],
        "permissions": {},
    },
    "brave-search": {
        "name": "Brave Search",
        "description": "Web search via Brave Search API",
        "package": "@modelcontextprotocol/server-brave-search",
        "bin": "mcp-server-brave-search",
        "category": "research",
        "platform": [],
        "risk_level": "low",
        "requires_config": ["BRAVE_API_KEY"],
        "permissions": {},
    },
    "fetch": {
        "name": "Fetch",
        "description": "Fetch and convert web content (HTML -> markdown)",
        "package": "@modelcontextprotocol/server-fetch",
        "bin": "mcp-server-fetch",
        "category": "research",
        "platform": [],
        "risk_level": "low",
        "requires_config": [],
        "permissions": {},
    },
    "github": {
        "name": "GitHub",
        "description": "Repos, issues, PRs, files, search",
        "package": "@modelcontextprotocol/server-github",
        "bin": "mcp-server-github",
        "category": "development",
        "platform": [],
        "risk_level": "medium",
        "requires_config": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
        "permissions": {},
    },
    "postgres": {
        "name": "PostgreSQL",
        "description": "Query a PostgreSQL database (read-only by default)",
        "package": "@modelcontextprotocol/server-postgres",
        "bin": "mcp-server-postgres",
        "category": "data",
        "platform": [],
        "risk_level": "high",
        "requires_config": ["POSTGRES_URL"],
        "permissions": {},
    },
    "puppeteer": {
        "name": "Puppeteer",
        "description": "Browser automation and scraping",
        "package": "@modelcontextprotocol/server-puppeteer",
        "bin": "mcp-server-puppeteer",
        "category": "research",
        "platform": [],
        "risk_level": "medium",
        "requires_config": [],
        "permissions": {},
    },
    "sequential-thinking": {
        "name": "Sequential Thinking",
        "description": "Structured multi-step reasoning helper",
        "package": "@modelcontextprotocol/server-sequential-thinking",
        "bin": "mcp-server-sequential-thinking",
        "category": "reasoning",
        "platform": [],
        "risk_level": "low",
        "requires_config": [],
        "permissions": {},
    },
    "memory": {
        "name": "Memory",
        "description": "Persistent knowledge graph across sessions",
        "package": "@modelcontextprotocol/server-memory",
        "bin": "mcp-server-memory",
        "category": "reasoning",
        "platform": [],
        "risk_level": "low",
        "requires_config": [],
        "permissions": {},
    },
    "slack": {
        "name": "Slack",
        "description": "Read and send Slack messages",
        "package": "@modelcontextprotocol/server-slack",
        "bin": "mcp-server-slack",
        "category": "productivity",
        "platform": [],
        "risk_level": "medium",
        "requires_config": ["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"],
        "permissions": {},
    },
    "time": {
        "name": "Time",
        "description": "Timezone-aware time and date utilities",
        "package": "@modelcontextprotocol/server-time",
        "bin": "mcp-server-time",
        "category": "utility",
        "platform": [],
        "risk_level": "low",
        "requires_config": [],
        "permissions": {},
    },
}

# Validate on module import — fail loudly if catalog is malformed
for _sid, _entry in CATALOG.items():
    validate_entry(_sid, _entry)
