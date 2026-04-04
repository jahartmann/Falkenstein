# Smart Assistant Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Umbau von 7-Agenten-Simulation zu 1 MainAgent + SubAgents on demand mit Telegram-Steuerung und Obsidian-Wissensbasis.

**Architecture:** MainAgent empfängt Input (Telegram/Obsidian), klassifiziert per LLM (quick_reply vs task), antwortet direkt oder spawnt einen spezialisierten SubAgent. Ergebnisse landen in Obsidian mit Kanban-Tracking. Büro-UI zeigt nur aktive Agents.

**Tech Stack:** FastAPI, aiosqlite, Ollama (Gemma 4), httpx (Telegram), watchdog (Obsidian), Phaser.js 3.80

---

## File Structure

### New files:
- `backend/main_agent.py` — MainAgent: classification, routing, direct replies
- `backend/sub_agent.py` — Lightweight SubAgent class with focused tool sets
- `backend/obsidian_writer.py` — Kanban updates, result routing to correct folders, frontmatter

### Modified files:
- `backend/models.py` — Simplified enums (AgentRole, AgentState)
- `backend/config.py` — New config field `LLM_BACKEND`
- `backend/telegram_bot.py` — Simplified: everything through MainAgent
- `backend/obsidian_watcher.py` — Direct callback to MainAgent instead of NotificationRouter
- `backend/main.py` — Slim lifespan, no sim loop
- `backend/tools/obsidian_manager.py` — Add `Ergebnisse/` subdirectories to vault structure
- `frontend/game.js` — Passive dashboard, no player character
- `frontend/agents.js` — No idle FSM, only show active agents

### Files to delete (Task 9):
- `backend/sim_engine.py`
- `backend/pm_logic.py`
- `backend/team_lead.py`
- `backend/personality.py`
- `backend/relationships.py`
- `backend/orchestrator.py`
- `backend/notification_router.py`
- `backend/agent_pool.py`

### Test files:
- `tests/test_main_agent.py`
- `tests/test_sub_agent.py`
- `tests/test_obsidian_writer.py`
- `tests/test_smart_telegram.py`
- `tests/test_smart_integration.py`

---

### Task 1: Simplify Models

**Files:**
- Modify: `backend/models.py`
- Test: `tests/test_models_v2.py`

- [ ] **Step 1: Write failing test for new enums**

```python
# tests/test_models_v2.py
from backend.models import AgentRole, AgentState, SubAgentType


def test_agent_role_has_main():
    assert AgentRole.MAIN == "main"


def test_agent_role_has_sub_types():
    assert AgentRole.CODER == "coder"
    assert AgentRole.RESEARCHER == "researcher"
    assert AgentRole.WRITER == "writer"
    assert AgentRole.OPS == "ops"


def test_agent_state_simplified():
    assert AgentState.IDLE == "idle"
    assert AgentState.WORKING == "working"


def test_sub_agent_type():
    assert SubAgentType.CODER == "coder"
    assert SubAgentType.RESEARCHER == "researcher"
    assert SubAgentType.WRITER == "writer"
    assert SubAgentType.OPS == "ops"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models_v2.py -v`
Expected: FAIL — SubAgentType not defined, AgentRole.MAIN not found

- [ ] **Step 3: Update models**

Replace the enums in `backend/models.py`:

```python
class AgentRole(str, Enum):
    MAIN = "main"
    CODER = "coder"
    RESEARCHER = "researcher"
    WRITER = "writer"
    OPS = "ops"


class AgentState(str, Enum):
    IDLE = "idle"
    WORKING = "working"


class SubAgentType(str, Enum):
    CODER = "coder"
    RESEARCHER = "researcher"
    WRITER = "writer"
    OPS = "ops"
```

Keep `TaskData`, `TaskStatus`, `MessageData`, `MessageType`, `AgentData`, `Position` unchanged.
Remove `AgentTraits`, `AgentMood`, `RelationshipData` — no longer needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models_v2.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/models.py tests/test_models_v2.py
git commit -m "refactor: simplify models for smart assistant architecture"
```

---

### Task 2: ObsidianWriter — Kanban & Result Routing

**Files:**
- Create: `backend/obsidian_writer.py`
- Modify: `backend/tools/obsidian_manager.py` (add Ergebnisse subdirs to vault structure)
- Test: `tests/test_obsidian_writer.py`

- [ ] **Step 1: Update vault structure in obsidian_manager.py**

Add the `Ergebnisse` subdirectories to `VAULT_STRUCTURE` in `backend/tools/obsidian_manager.py`:

```python
VAULT_STRUCTURE = {
    VAULT_PREFIX: {
        "Falkenstein": {
            "Projekte": {},
            "Tasks": {},
            "Daily Reports": {},
            "Notizen": {},
            "Ergebnisse": {
                "Recherchen": {},
                "Guides": {},
                "Cheat-Sheets": {},
                "Reports": {},
                "Code": {},
            },
        },
        "Management": {
            "Inbox.md": "# Inbox\n\nHier landen neue Aufgaben und Ideen.\n",
            "Kanban.md": (
                "# Kanban Board\n\n"
                "## Backlog\n\n## In Progress\n\n## Done\n\n## Archiv\n"
            ),
        },
    },
}
```

- [ ] **Step 2: Write failing tests for ObsidianWriter**

```python
# tests/test_obsidian_writer.py
import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.obsidian_writer import ObsidianWriter


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a minimal vault structure for testing."""
    vault = tmp_path / "TestVault"
    vault.mkdir()
    ki = vault / "KI-Büro"
    ki.mkdir()
    mgmt = ki / "Management"
    mgmt.mkdir()
    kanban = mgmt / "Kanban.md"
    kanban.write_text(
        "# Kanban Board\n\n## Backlog\n\n## In Progress\n\n## Done\n\n## Archiv\n"
    )
    tasks = ki / "Falkenstein" / "Tasks"
    tasks.mkdir(parents=True)
    for sub in ["Recherchen", "Guides", "Cheat-Sheets", "Reports", "Code"]:
        (ki / "Falkenstein" / "Ergebnisse" / sub).mkdir(parents=True)
    (ki / "Falkenstein" / "Daily Reports").mkdir(parents=True)
    return vault


@pytest.fixture
def writer(tmp_vault):
    return ObsidianWriter(vault_path=tmp_vault)


def test_create_task_note(writer, tmp_vault):
    path = writer.create_task_note(
        title="Docker vs Podman recherchieren",
        typ="recherche",
        agent="researcher",
    )
    assert path.exists()
    content = path.read_text()
    assert "typ: recherche" in content
    assert "status: backlog" in content
    assert "agent: researcher" in content
    assert "# Docker vs Podman recherchieren" in content


def test_kanban_add_backlog(writer, tmp_vault):
    writer.create_task_note(title="Test Task", typ="code", agent="coder")
    writer.kanban_move("Test Task", "backlog")
    kanban = (tmp_vault / "KI-Büro" / "Management" / "Kanban.md").read_text()
    assert "[[" in kanban  # has wikilink
    assert "Test Task" in kanban
    # Should be under Backlog
    backlog_pos = kanban.index("## Backlog")
    in_progress_pos = kanban.index("## In Progress")
    task_pos = kanban.index("Test Task")
    assert backlog_pos < task_pos < in_progress_pos


def test_kanban_move_to_in_progress(writer, tmp_vault):
    writer.create_task_note(title="Moving Task", typ="code", agent="coder")
    writer.kanban_move("Moving Task", "backlog")
    writer.kanban_move("Moving Task", "in_progress")
    kanban = (tmp_vault / "KI-Büro" / "Management" / "Kanban.md").read_text()
    in_progress_pos = kanban.index("## In Progress")
    done_pos = kanban.index("## Done")
    task_pos = kanban.index("Moving Task")
    assert in_progress_pos < task_pos < done_pos


def test_kanban_move_to_done(writer, tmp_vault):
    writer.create_task_note(title="Done Task", typ="recherche", agent="researcher")
    writer.kanban_move("Done Task", "backlog")
    writer.kanban_move("Done Task", "done")
    kanban = (tmp_vault / "KI-Büro" / "Management" / "Kanban.md").read_text()
    assert "- [x]" in kanban  # checked off


def test_write_result_recherche(writer, tmp_vault):
    path = writer.write_result(
        title="Docker vs Podman",
        typ="recherche",
        content="# Docker vs Podman\n\nDocker ist...",
    )
    assert "Recherchen" in str(path)
    assert path.exists()
    assert "Docker ist" in path.read_text()


def test_write_result_guide(writer, tmp_vault):
    path = writer.write_result(
        title="Git Rebase Guide",
        typ="guide",
        content="# Git Rebase\n\nSchritt 1...",
    )
    assert "Guides" in str(path)


def test_write_result_cheat_sheet(writer, tmp_vault):
    path = writer.write_result(
        title="Docker Commands",
        typ="cheat-sheet",
        content="# Docker Cheat Sheet",
    )
    assert "Cheat-Sheets" in str(path)


def test_write_result_code(writer, tmp_vault):
    path = writer.write_result(
        title="Backup Script",
        typ="code",
        content="# Backup Script\n\n```bash\nrsync...\n```",
    )
    assert "Code" in str(path)


def test_update_task_note_status(writer, tmp_vault):
    path = writer.create_task_note(title="Status Test", typ="code", agent="coder")
    writer.update_task_status(path, "in_progress")
    content = path.read_text()
    assert "status: in_progress" in content


def test_result_type_mapping(writer):
    assert writer.map_result_type("recherche") == "Recherchen"
    assert writer.map_result_type("guide") == "Guides"
    assert writer.map_result_type("cheat-sheet") == "Cheat-Sheets"
    assert writer.map_result_type("code") == "Code"
    assert writer.map_result_type("report") == "Reports"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_obsidian_writer.py -v`
Expected: FAIL — `backend.obsidian_writer` not found

- [ ] **Step 4: Implement ObsidianWriter**

```python
# backend/obsidian_writer.py
import datetime
import re
from pathlib import Path

VAULT_PREFIX = "KI-Büro"

# Map task types to Ergebnisse subdirectories
_RESULT_TYPE_MAP = {
    "recherche": "Recherchen",
    "guide": "Guides",
    "cheat-sheet": "Cheat-Sheets",
    "code": "Code",
    "report": "Reports",
}

# Kanban section headers in order
_KANBAN_SECTIONS = ["## Backlog", "## In Progress", "## Done", "## Archiv"]


class ObsidianWriter:
    """Manages Kanban board, task notes, and result files in Obsidian vault."""

    def __init__(self, vault_path: Path):
        self.vault = vault_path.resolve()
        self.kanban_path = self.vault / VAULT_PREFIX / "Management" / "Kanban.md"
        self.tasks_dir = self.vault / VAULT_PREFIX / "Falkenstein" / "Tasks"
        self.results_dir = self.vault / VAULT_PREFIX / "Falkenstein" / "Ergebnisse"
        self.reports_dir = self.vault / VAULT_PREFIX / "Falkenstein" / "Daily Reports"

    def map_result_type(self, typ: str) -> str:
        return _RESULT_TYPE_MAP.get(typ, "Reports")

    def create_task_note(self, title: str, typ: str, agent: str) -> Path:
        """Create a task note with YAML frontmatter. Returns the file path."""
        today = datetime.date.today().isoformat()
        slug = re.sub(r"[^\w\s-]", "", title.lower())
        slug = re.sub(r"\s+", "-", slug.strip())[:60]
        filename = f"{today}-{slug}.md"
        path = self.tasks_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)

        frontmatter = (
            f"---\n"
            f"typ: {typ}\n"
            f"status: backlog\n"
            f"agent: {agent}\n"
            f"erstellt: {today}\n"
            f"---\n\n"
            f"# {title}\n"
        )
        path.write_text(frontmatter, encoding="utf-8")
        return path

    def update_task_status(self, path: Path, status: str):
        """Update the status field in a task note's frontmatter."""
        if not path.exists():
            return
        content = path.read_text(encoding="utf-8")
        content = re.sub(r"status: \w+", f"status: {status}", content, count=1)
        path.write_text(content, encoding="utf-8")

    def kanban_move(self, title: str, target_section: str):
        """Move a task entry to a target section in Kanban.md.

        target_section: 'backlog', 'in_progress', 'done', 'archiv'
        """
        section_map = {
            "backlog": "## Backlog",
            "in_progress": "## In Progress",
            "done": "## Done",
            "archiv": "## Archiv",
        }
        target_header = section_map.get(target_section, "## Backlog")

        if not self.kanban_path.exists():
            return

        text = self.kanban_path.read_text(encoding="utf-8")

        # Find the task note filename for wikilink
        today = datetime.date.today().isoformat()
        slug = re.sub(r"[^\w\s-]", "", title.lower())
        slug = re.sub(r"\s+", "-", slug.strip())[:60]
        note_name = f"{today}-{slug}"

        # Build the entry line
        checkbox = "[x]" if target_section == "done" else "[ ]"
        entry = f"- [{checkbox[1]}] [[Tasks/{note_name}|{title}]]"

        # Remove existing entry for this task (if moving)
        # Match any line containing the task title wikilink
        lines = text.split("\n")
        lines = [l for l in lines if title not in l or "## " in l]
        text = "\n".join(lines)

        # Insert under target section
        idx = text.index(target_header)
        insert_pos = idx + len(target_header)
        text = text[:insert_pos] + f"\n{entry}" + text[insert_pos:]

        self.kanban_path.write_text(text, encoding="utf-8")

    def write_result(self, title: str, typ: str, content: str) -> Path:
        """Write a result file to the appropriate Ergebnisse subdirectory."""
        subdir = self.map_result_type(typ)
        today = datetime.date.today().isoformat()
        slug = re.sub(r"[^\w\s-]", "", title.lower())
        slug = re.sub(r"\s+", "-", slug.strip())[:60]
        filename = f"{today}-{slug}.md"
        path = self.results_dir / subdir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_obsidian_writer.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/obsidian_writer.py backend/tools/obsidian_manager.py tests/test_obsidian_writer.py
git commit -m "feat: ObsidianWriter with Kanban tracking and result routing"
```

---

### Task 3: SubAgent — Lightweight Task Executor

**Files:**
- Create: `backend/sub_agent.py`
- Test: `tests/test_sub_agent.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sub_agent.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.sub_agent import SubAgent, SUB_AGENT_TOOLS


def test_tool_sets_are_defined():
    assert "coder" in SUB_AGENT_TOOLS
    assert "researcher" in SUB_AGENT_TOOLS
    assert "writer" in SUB_AGENT_TOOLS
    assert "ops" in SUB_AGENT_TOOLS


def test_coder_has_correct_tools():
    assert "shell_runner" in SUB_AGENT_TOOLS["coder"]
    assert "code_executor" in SUB_AGENT_TOOLS["coder"]


def test_researcher_has_correct_tools():
    assert "web_surfer" in SUB_AGENT_TOOLS["researcher"]
    assert "vision" in SUB_AGENT_TOOLS["researcher"]


def test_writer_has_correct_tools():
    assert "obsidian_manager" in SUB_AGENT_TOOLS["writer"]


def test_ops_has_correct_tools():
    assert "shell_runner" in SUB_AGENT_TOOLS["ops"]


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.chat_with_tools = AsyncMock(return_value={
        "content": "Done. Here is the result.",
    })
    return llm


@pytest.fixture
def mock_tools():
    registry = MagicMock()
    tool = AsyncMock()
    tool.execute = AsyncMock(return_value=MagicMock(success=True, output="tool output"))
    tool.schema.return_value = {"type": "object", "properties": {}}
    registry.get.return_value = tool
    return registry


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.log_tool_use = AsyncMock()
    return db


def test_sub_agent_creation(mock_llm, mock_tools, mock_db):
    agent = SubAgent(
        agent_type="coder",
        task_description="Write a backup script",
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
    )
    assert agent.agent_type == "coder"
    assert agent.agent_id.startswith("sub_coder_")


@pytest.mark.asyncio
async def test_sub_agent_run_returns_result(mock_llm, mock_tools, mock_db):
    # LLM returns content without tool calls -> direct answer
    mock_llm.chat_with_tools = AsyncMock(return_value={
        "content": "The backup script is: rsync -av ...",
    })
    agent = SubAgent(
        agent_type="coder",
        task_description="Write a backup script",
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
    )
    result = await agent.run()
    assert "rsync" in result
    assert agent.done


@pytest.mark.asyncio
async def test_sub_agent_max_iterations(mock_llm, mock_tools, mock_db):
    # LLM always returns tool calls, never finishes
    mock_llm.chat_with_tools = AsyncMock(return_value={
        "content": "",
        "tool_calls": [{"function": {"name": "shell_runner", "arguments": {"command": "ls"}}}],
    })
    agent = SubAgent(
        agent_type="coder",
        task_description="Infinite loop task",
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
        max_iterations=3,
    )
    result = await agent.run()
    # Should stop after max_iterations
    assert agent.done
    assert mock_llm.chat_with_tools.call_count <= 4  # 3 iterations + 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sub_agent.py -v`
Expected: FAIL — `backend.sub_agent` not found

- [ ] **Step 3: Implement SubAgent**

```python
# backend/sub_agent.py
import uuid
from backend.tools.base import ToolRegistry, ToolResult

# Which tools each sub-agent type can use
SUB_AGENT_TOOLS: dict[str, list[str]] = {
    "coder": ["shell_runner", "code_executor", "cli_bridge"],
    "researcher": ["web_surfer", "vision", "cli_bridge"],
    "writer": ["obsidian_manager", "cli_bridge"],
    "ops": ["shell_runner", "cli_bridge"],
}

# System prompts per type
_SYSTEM_PROMPTS: dict[str, str] = {
    "coder": (
        "Du bist ein Coding-Agent. Du schreibst, debuggst und optimierst Code. "
        "Nutze die verfügbaren Tools um die Aufgabe zu erledigen. "
        "Antworte am Ende mit einer klaren Zusammenfassung des Ergebnisses auf Deutsch."
    ),
    "researcher": (
        "Du bist ein Research-Agent. Du recherchierst Themen gründlich im Web. "
        "Nutze die verfügbaren Tools um Informationen zu sammeln. "
        "Antworte am Ende mit einem strukturierten Ergebnis auf Deutsch."
    ),
    "writer": (
        "Du bist ein Writer-Agent. Du erstellst Texte, Dokumentation und Reports. "
        "Nutze die verfügbaren Tools um Inhalte zu erstellen. "
        "Antworte am Ende mit dem fertigen Text auf Deutsch."
    ),
    "ops": (
        "Du bist ein Ops-Agent. Du verwaltest Systeme, führst Befehle aus und löst Infrastruktur-Probleme. "
        "Nutze die verfügbaren Tools um die Aufgabe zu erledigen. "
        "Antworte am Ende mit einer klaren Zusammenfassung auf Deutsch."
    ),
}


class SubAgent:
    """Lightweight, short-lived agent that executes a single task with focused tools."""

    def __init__(
        self,
        agent_type: str,
        task_description: str,
        llm,
        tools: ToolRegistry,
        db,
        max_iterations: int = 10,
    ):
        self.agent_type = agent_type
        self.agent_id = f"sub_{agent_type}_{uuid.uuid4().hex[:8]}"
        self.task_description = task_description
        self.llm = llm
        self.tools = tools
        self.db = db
        self.max_iterations = max_iterations
        self.done = False
        self._messages: list[dict] = []

        # Filter tools to only what this agent type needs
        allowed = SUB_AGENT_TOOLS.get(agent_type, [])
        self._tool_schemas = []
        self._tool_map: dict[str, object] = {}
        for name in allowed:
            tool = tools.get(name)
            if tool:
                self._tool_map[name] = tool
                self._tool_schemas.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.schema(),
                    },
                })

    async def run(self) -> str:
        """Execute the task. Returns the final result string."""
        system = _SYSTEM_PROMPTS.get(self.agent_type, _SYSTEM_PROMPTS["ops"])
        self._messages = [{"role": "user", "content": self.task_description}]

        for _ in range(self.max_iterations):
            if self._tool_schemas:
                response = await self.llm.chat_with_tools(
                    system_prompt=system,
                    messages=self._messages,
                    tools=self._tool_schemas,
                )
            else:
                content = await self.llm.chat(
                    system_prompt=system,
                    messages=self._messages,
                )
                response = {"content": content}

            tool_calls = response.get("tool_calls", [])
            content = response.get("content", "")

            # No tool calls -> agent is done
            if not tool_calls:
                self.done = True
                return content or "Task abgeschlossen (keine Ausgabe)."

            # Execute tool calls
            self._messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                args = func.get("arguments", {})
                tool = self._tool_map.get(tool_name)
                if tool:
                    result = await tool.execute(args)
                    await self.db.log_tool_use(
                        self.agent_id, tool_name, args, result.output, result.success
                    )
                    self._messages.append({
                        "role": "tool",
                        "content": result.output[:5000],
                    })
                else:
                    self._messages.append({
                        "role": "tool",
                        "content": f"Tool '{tool_name}' nicht verfügbar.",
                    })

        # Max iterations reached
        self.done = True
        last_content = self._messages[-1].get("content", "") if self._messages else ""
        return last_content or "Max Iterationen erreicht."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sub_agent.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/sub_agent.py tests/test_sub_agent.py
git commit -m "feat: SubAgent class with focused tool sets"
```

---

### Task 4: MainAgent — Brain of the System

**Files:**
- Create: `backend/main_agent.py`
- Test: `tests/test_main_agent.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_main_agent.py
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.main_agent import MainAgent


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def mock_tools():
    return MagicMock()


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.create_task = AsyncMock(return_value=1)
    db.update_task_status = AsyncMock()
    db.update_task_result = AsyncMock()
    return db


@pytest.fixture
def mock_obsidian_writer():
    writer = MagicMock()
    writer.create_task_note = MagicMock(return_value=MagicMock())
    writer.kanban_move = MagicMock()
    writer.write_result = MagicMock(return_value=MagicMock())
    writer.update_task_status = MagicMock()
    return writer


@pytest.fixture
def mock_telegram():
    tg = AsyncMock()
    tg.send_message = AsyncMock(return_value=True)
    return tg


@pytest.fixture
def agent(mock_llm, mock_tools, mock_db, mock_obsidian_writer, mock_telegram):
    return MainAgent(
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
        obsidian_writer=mock_obsidian_writer,
        telegram=mock_telegram,
    )


@pytest.mark.asyncio
async def test_classify_quick_reply(agent, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "quick_reply", "answer": "Es geht mir gut!"}')
    result = await agent.classify("Wie geht es dir?")
    assert result["type"] == "quick_reply"


@pytest.mark.asyncio
async def test_classify_task(agent, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "task", "agent": "researcher", "result_type": "recherche", "title": "Docker vs Podman"}')
    result = await agent.classify("Recherchiere Docker vs Podman")
    assert result["type"] == "task"
    assert result["agent"] == "researcher"


@pytest.mark.asyncio
async def test_handle_quick_reply(agent, mock_llm, mock_telegram):
    mock_llm.chat = AsyncMock(return_value='{"type": "quick_reply", "answer": "Alles läuft!"}')
    await agent.handle_message("Was ist der Status?", chat_id="123")
    mock_telegram.send_message.assert_called()
    call_args = mock_telegram.send_message.call_args
    assert "Alles läuft!" in call_args[0][0]


@pytest.mark.asyncio
async def test_handle_task_sends_confirmation(agent, mock_llm, mock_telegram, mock_db):
    mock_llm.chat = AsyncMock(return_value='{"type": "task", "agent": "coder", "result_type": "code", "title": "Backup Script"}')
    # Mock SubAgent.run to return quickly
    with patch("backend.main_agent.SubAgent") as MockSub:
        mock_sub = AsyncMock()
        mock_sub.run = AsyncMock(return_value="Script erstellt: rsync ...")
        mock_sub.agent_id = "sub_coder_abc123"
        mock_sub.agent_type = "coder"
        MockSub.return_value = mock_sub
        await agent.handle_message("Schreib ein Backup Script", chat_id="123")
    # Should have sent at least a confirmation message
    assert mock_telegram.send_message.call_count >= 1


@pytest.mark.asyncio
async def test_active_agents_tracking(agent, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "task", "agent": "coder", "result_type": "code", "title": "Test"}')
    with patch("backend.main_agent.SubAgent") as MockSub:
        mock_sub = AsyncMock()
        mock_sub.run = AsyncMock(return_value="Done")
        mock_sub.agent_id = "sub_coder_abc123"
        mock_sub.agent_type = "coder"
        mock_sub.done = True
        MockSub.return_value = mock_sub
        # During execution, agent should be tracked
        assert len(agent.active_agents) == 0
        await agent.handle_message("Test task", chat_id="123")
        # After completion, should be removed
        assert len(agent.active_agents) == 0


def test_get_status(agent):
    status = agent.get_status()
    assert "active_agents" in status
    assert isinstance(status["active_agents"], list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main_agent.py -v`
Expected: FAIL — `backend.main_agent` not found

- [ ] **Step 3: Implement MainAgent**

```python
# backend/main_agent.py
import asyncio
import json
import re
from backend.sub_agent import SubAgent
from backend.obsidian_writer import ObsidianWriter
from backend.models import TaskData, TaskStatus

_CLASSIFY_SYSTEM = (
    "Du bist ein Assistent-Router. Analysiere die Nachricht und entscheide:\n"
    "1. quick_reply — Direkt beantwortbar (Fragen, Status, Smalltalk, kurze Infos)\n"
    "2. task — Braucht Arbeit (Recherche, Code, Texte schreiben, System-Tasks)\n\n"
    "Bei quick_reply: Beantworte die Frage direkt.\n"
    "Bei task: Bestimme den passenden Agent-Typ und Ergebnis-Typ.\n\n"
    "Agent-Typen: coder, researcher, writer, ops\n"
    "Ergebnis-Typen: recherche, guide, cheat-sheet, code, report\n\n"
    "Antworte NUR mit JSON:\n"
    '- quick_reply: {"type": "quick_reply", "answer": "<deine Antwort>"}\n'
    '- task: {"type": "task", "agent": "<typ>", "result_type": "<typ>", "title": "<kurzer Titel>"}'
)


class MainAgent:
    """Central brain: classifies input, answers directly or spawns SubAgents."""

    def __init__(self, llm, tools, db, obsidian_writer: ObsidianWriter,
                 telegram=None, ws_callback=None):
        self.llm = llm
        self.tools = tools
        self.db = db
        self.obsidian_writer = obsidian_writer
        self.telegram = telegram
        self.ws_callback = ws_callback  # async callback for WebSocket broadcasts
        self.active_agents: dict[str, dict] = {}  # agent_id -> {type, task, sub_agent}
        self._chat_history: dict[str, list[dict]] = {}
        self._max_history = 20

    async def classify(self, message: str) -> dict:
        """Classify a message as quick_reply or task."""
        response = await self.llm.chat(
            system_prompt=_CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": message}],
            temperature=0.1,
        )
        # Parse JSON from response
        try:
            text = response.strip()
            if "{" in text:
                text = text[text.index("{"):text.rindex("}") + 1]
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            # Fallback: treat as quick_reply with the raw response
            return {"type": "quick_reply", "answer": response}

    async def handle_message(self, text: str, chat_id: str = ""):
        """Handle an incoming message from Telegram or Obsidian."""
        classification = await self.classify(text)
        msg_type = classification.get("type", "quick_reply")

        if msg_type == "quick_reply":
            answer = classification.get("answer", "Ich habe keine Antwort.")
            if self.telegram:
                await self.telegram.send_message(answer[:4000], chat_id=chat_id or None)
        elif msg_type == "task":
            await self._handle_task(classification, text, chat_id)

    async def _handle_task(self, classification: dict, original_text: str, chat_id: str):
        """Spawn a SubAgent for a task."""
        agent_type = classification.get("agent", "ops")
        result_type = classification.get("result_type", "report")
        title = classification.get("title", original_text[:80])

        # Create task in DB
        task = TaskData(title=title, description=original_text, status=TaskStatus.OPEN)
        task_id = await self.db.create_task(task)

        # Create task note + Kanban entry
        task_path = self.obsidian_writer.create_task_note(
            title=title, typ=result_type, agent=agent_type,
        )
        self.obsidian_writer.kanban_move(title, "backlog")

        # Send confirmation via Telegram
        if self.telegram:
            await self.telegram.send_message(
                f"👍 Arbeite daran: {title}\n🤖 Agent: {agent_type}",
                chat_id=chat_id or None,
            )

        # Update status
        await self.db.update_task_status(task_id, TaskStatus.IN_PROGRESS, agent_type)
        self.obsidian_writer.kanban_move(title, "in_progress")
        self.obsidian_writer.update_task_status(task_path, "in_progress")

        # Spawn SubAgent
        sub = SubAgent(
            agent_type=agent_type,
            task_description=original_text,
            llm=self.llm,
            tools=self.tools,
            db=self.db,
        )
        self.active_agents[sub.agent_id] = {
            "type": agent_type,
            "task": title,
            "task_id": task_id,
            "sub_agent": sub,
        }

        # Broadcast agent_spawned
        if self.ws_callback:
            await self.ws_callback({
                "type": "agent_spawned",
                "agent_id": sub.agent_id,
                "agent_type": agent_type,
                "task": title,
            })

        # Run SubAgent async
        try:
            result = await sub.run()

            # Write result to Obsidian
            result_path = self.obsidian_writer.write_result(
                title=title, typ=result_type, content=result,
            )

            # Update DB + Kanban
            await self.db.update_task_result(task_id, result[:5000])
            await self.db.update_task_status(task_id, TaskStatus.DONE)
            self.obsidian_writer.kanban_move(title, "done")
            self.obsidian_writer.update_task_status(task_path, "done")

            # Send result summary via Telegram
            if self.telegram:
                summary = result[:500] if len(result) <= 500 else result[:497] + "..."
                await self.telegram.send_message(
                    f"✅ Fertig: {title}\n\n{summary}\n\n📁 Ergebnis in Obsidian",
                    chat_id=chat_id or None,
                )

            # Broadcast agent_done
            if self.ws_callback:
                await self.ws_callback({
                    "type": "agent_done",
                    "agent_id": sub.agent_id,
                    "agent_type": agent_type,
                    "task": title,
                })

        except Exception as e:
            await self.db.update_task_status(task_id, TaskStatus.FAILED)
            if self.telegram:
                await self.telegram.send_message(
                    f"❌ Fehler bei: {title}\n{str(e)[:300]}",
                    chat_id=chat_id or None,
                )
        finally:
            self.active_agents.pop(sub.agent_id, None)

    def get_status(self) -> dict:
        """Get current status for /status command and frontend."""
        return {
            "active_agents": [
                {"agent_id": aid, "type": info["type"], "task": info["task"]}
                for aid, info in self.active_agents.items()
            ],
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_main_agent.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main_agent.py tests/test_main_agent.py
git commit -m "feat: MainAgent with classification and SubAgent spawning"
```

---

### Task 5: Refactor Telegram Bot

**Files:**
- Modify: `backend/telegram_bot.py`
- Test: `tests/test_smart_telegram.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_smart_telegram.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.telegram_bot import TelegramBot


@pytest.fixture
def bot():
    with patch.object(TelegramBot, '__init__', lambda self: None):
        b = TelegramBot.__new__(TelegramBot)
        b.token = "fake"
        b.chat_id = "123"
        b.base_url = "https://api.telegram.org/botfake"
        b._offset = 0
        b._handlers = []
        b._started = False
        return b


def test_enabled(bot):
    assert bot.enabled


def test_on_message_registers_handler(bot):
    handler = AsyncMock()
    bot.on_message(handler)
    assert handler in bot._handlers


@pytest.mark.asyncio
async def test_send_message_calls_api(bot):
    with patch("httpx.AsyncClient") as MockClient:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        MockClient.return_value = mock_client
        result = await bot.send_message("Hello")
        assert result is True
```

- [ ] **Step 2: Run tests to verify they pass** (existing bot structure is unchanged)

Run: `python -m pytest tests/test_smart_telegram.py -v`
Expected: PASS — existing bot API is compatible

- [ ] **Step 3: Simplify TelegramBot — remove unused convenience methods**

In `backend/telegram_bot.py`, remove the following methods that are no longer needed (MainAgent handles all notifications now):
- `notify_task_assigned`
- `notify_task_done`
- `notify_task_failed`
- `notify_escalation`
- `notify_budget_warning`

Keep: `__init__`, `enabled`, `on_message`, `send_message`, `poll_updates`, `poll_loop`.

The file should look like:

```python
# backend/telegram_bot.py
import asyncio
import httpx
from backend.config import settings


class TelegramBot:
    """Telegram Bot — thin transport layer. All logic is in MainAgent."""

    def __init__(self):
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self._offset: int = 0
        self._handlers: list = []
        self._started: bool = False

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def on_message(self, handler):
        self._handlers.append(handler)

    async def send_message(self, text: str, chat_id: str | None = None) -> bool:
        if not self.enabled:
            return False
        target = chat_id or self.chat_id
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={"chat_id": target, "text": text, "parse_mode": "Markdown"},
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def poll_updates(self) -> list[dict]:
        if not self.enabled:
            return []
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                resp = await client.get(
                    f"{self.base_url}/getUpdates",
                    params={"offset": self._offset, "timeout": 30},
                )
                if resp.status_code != 200:
                    return []
                data = resp.json()
                results = data.get("result", [])
                messages = []
                for update in results:
                    self._offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    if text:
                        messages.append({
                            "text": text,
                            "chat_id": str(msg["chat"]["id"]),
                            "from": msg.get("from", {}).get("first_name", "Unknown"),
                        })
                return messages
        except Exception:
            return []

    async def poll_loop(self):
        if not self._started:
            await self.poll_updates()
            self._started = True

        while True:
            try:
                messages = await self.poll_updates()
                for msg in messages:
                    for handler in self._handlers:
                        await handler(msg)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_smart_telegram.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/telegram_bot.py tests/test_smart_telegram.py
git commit -m "refactor: simplify TelegramBot to thin transport layer"
```

---

### Task 6: Refactor Obsidian Watcher

**Files:**
- Modify: `backend/obsidian_watcher.py`
- Test: `tests/test_smart_watcher.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_smart_watcher.py
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.obsidian_watcher import ObsidianWatcher


@pytest.fixture
def tmp_vault(tmp_path):
    inbox = tmp_path / "KI-Büro" / "Management"
    inbox.mkdir(parents=True)
    (inbox / "Inbox.md").write_text("# Inbox\n")
    return tmp_path


def test_watcher_accepts_callback(tmp_vault):
    callback = AsyncMock()
    watcher = ObsidianWatcher(
        vault_path=tmp_vault,
        on_new_todo=callback,
    )
    assert watcher._on_new_todo is callback


def test_watcher_has_no_router_dependency(tmp_vault):
    """Watcher should not require a NotificationRouter."""
    callback = AsyncMock()
    watcher = ObsidianWatcher(
        vault_path=tmp_vault,
        on_new_todo=callback,
    )
    assert not hasattr(watcher, 'router') or watcher.router is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_smart_watcher.py -v`
Expected: FAIL — constructor signature doesn't match

- [ ] **Step 3: Refactor ObsidianWatcher**

Change `backend/obsidian_watcher.py` to accept a simple async callback instead of `NotificationRouter`:

Replace the `__init__` signature:

```python
# Old:
def __init__(self, vault_path: Path, router):
    ...
    self.router = router

# New:
def __init__(self, vault_path: Path, on_new_todo=None):
    ...
    self._on_new_todo = on_new_todo
```

Replace the `_process_new_todos` call that routes to `notification_router`:

```python
# Old (inside _process_new_todos or similar):
await self.router.route_event("todo_from_obsidian", {...})

# New:
if self._on_new_todo:
    await self._on_new_todo(content, source_file)
```

Keep the existing watchdog/filesystem logic, SHA256 hashing, and debounce unchanged.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_smart_watcher.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/obsidian_watcher.py tests/test_smart_watcher.py
git commit -m "refactor: ObsidianWatcher uses callback instead of NotificationRouter"
```

---

### Task 7: Rewrite main.py — Slim Lifespan

**Files:**
- Modify: `backend/main.py`
- Test: `tests/test_smart_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_smart_integration.py
"""Smoke tests for the new slim main.py structure."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_app_import():
    """The app should import without errors."""
    from backend.main import app
    assert app.title == "Falkenstein"


def test_app_has_required_routes():
    from backend.main import app
    routes = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/ws" in routes or any("/ws" in str(r) for r in app.routes)
    assert "/api/task" in routes
    assert "/api/agents" in routes
    assert "/api/tasks" in routes
    assert "/api/status" in routes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smart_integration.py -v`
Expected: FAIL — `/api/status` route doesn't exist yet

- [ ] **Step 3: Rewrite main.py**

Replace the entire `backend/main.py` with a slim version:

```python
# backend/main.py
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.config import settings
from backend.database import Database
from backend.llm_client import LLMClient
from backend.ws_manager import WSManager
from backend.telegram_bot import TelegramBot
from backend.main_agent import MainAgent
from backend.obsidian_writer import ObsidianWriter
from backend.obsidian_watcher import ObsidianWatcher
from backend.tools.base import ToolRegistry
from backend.tools.file_manager import FileManagerTool
from backend.tools.web_surfer import WebSurferTool
from backend.tools.shell_runner import ShellRunnerTool
from backend.tools.code_executor import CodeExecutorTool
from backend.tools.obsidian_manager import ObsidianManagerTool
from backend.tools.cli_bridge import CLIBridgeTool, CLIBudgetTracker
from backend.tools.vision import VisionTool

db: Database = None
ws_mgr = WSManager()
telegram: TelegramBot = None
main_agent: MainAgent = None
budget_tracker: CLIBudgetTracker = None
telegram_task: asyncio.Task = None
watcher_task: asyncio.Task = None


async def handle_telegram_message(msg: dict):
    """All Telegram messages go through MainAgent."""
    text = msg["text"].strip()
    chat_id = msg.get("chat_id", "")

    # Only /status and /stop are handled directly, everything else -> MainAgent
    if text.startswith("/status"):
        status = main_agent.get_status()
        agents = status["active_agents"]
        if not agents:
            await telegram.send_message("💤 Keine aktiven Agents.", chat_id=chat_id)
        else:
            lines = ["🏢 *Aktive Agents:*"]
            for a in agents:
                lines.append(f"  🤖 {a['type']}: {a['task']}")
            await telegram.send_message("\n".join(lines), chat_id=chat_id)
    elif text.startswith("/stop"):
        await telegram.send_message("⏹ Stop noch nicht implementiert.", chat_id=chat_id)
    elif text.startswith("/start") or text.startswith("/help"):
        await telegram.send_message(
            "🏢 *Falkenstein Assistent*\n\n"
            "Schick mir einfach eine Nachricht oder Aufgabe.\n\n"
            "/status — Aktive Agents\n"
            "/stop — Task abbrechen",
            chat_id=chat_id,
        )
    else:
        # Everything goes through MainAgent
        await main_agent.handle_message(text, chat_id=chat_id)


async def handle_obsidian_todo(content: str, source_file: str):
    """New todo from Obsidian Inbox -> MainAgent."""
    await main_agent.handle_message(content)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, telegram, telegram_task, main_agent, budget_tracker, watcher_task

    # Database
    db = Database(settings.db_path)
    await db.init()

    # LLM
    llm = LLMClient()

    # Tools
    tools = ToolRegistry()
    settings.workspace_path.mkdir(parents=True, exist_ok=True)
    tools.register(FileManagerTool(workspace_path=settings.workspace_path))
    tools.register(WebSurferTool())
    tools.register(ShellRunnerTool(workspace_path=settings.workspace_path))
    tools.register(CodeExecutorTool(workspace_path=settings.workspace_path))
    tools.register(ObsidianManagerTool(vault_path=settings.obsidian_vault_path))
    budget_tracker = CLIBudgetTracker(daily_budget=settings.cli_daily_token_budget)
    tools.register(CLIBridgeTool(
        workspace_path=settings.workspace_path,
        budget_tracker=budget_tracker,
        provider=settings.cli_provider,
    ))
    tools.register(VisionTool(workspace_path=settings.workspace_path, llm=llm))

    # Obsidian Writer
    obsidian_writer = ObsidianWriter(vault_path=settings.obsidian_vault_path)

    # Telegram
    telegram = TelegramBot()

    # MainAgent
    main_agent = MainAgent(
        llm=llm,
        tools=tools,
        db=db,
        obsidian_writer=obsidian_writer,
        telegram=telegram if telegram.enabled else None,
        ws_callback=ws_mgr.broadcast,
    )

    # Start Telegram polling
    if telegram.enabled:
        telegram.on_message(handle_telegram_message)
        telegram_task = asyncio.create_task(telegram.poll_loop())
        print("Telegram bot active")

    # Start Obsidian Watcher
    if settings.obsidian_watch_enabled and settings.obsidian_vault_path.exists():
        watcher = ObsidianWatcher(
            vault_path=settings.obsidian_vault_path,
            on_new_todo=handle_obsidian_todo,
        )
        watcher_task = asyncio.create_task(watcher.start())
        print("Obsidian watcher active")

    print(f"Falkenstein running on port {settings.frontend_port}")
    yield

    # Shutdown
    if telegram_task:
        telegram_task.cancel()
        try:
            await telegram_task
        except asyncio.CancelledError:
            pass
    if watcher_task:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
    await db.close()


app = FastAPI(title="Falkenstein", lifespan=lifespan)

frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/")
async def index():
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"status": "Falkenstein running"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_mgr.connect(ws)
    # Send current state
    status = main_agent.get_status() if main_agent else {"active_agents": []}
    await ws.send_json({"type": "full_state", **status})
    try:
        while True:
            data = await ws.receive_json()
            await handle_ws_message(data, ws)
    except WebSocketDisconnect:
        ws_mgr.disconnect(ws)


async def handle_ws_message(data: dict, ws: WebSocket):
    msg_type = data.get("type", "")
    if msg_type == "submit_task":
        text = data.get("description", data.get("title", ""))
        if text:
            await main_agent.handle_message(text)
    elif msg_type == "get_state":
        status = main_agent.get_status()
        await ws.send_json({"type": "state_update", **status})


@app.post("/api/task")
async def create_task(title: str, description: str = ""):
    await main_agent.handle_message(description or title)
    return {"status": "submitted"}


@app.get("/api/agents")
async def get_agents():
    if main_agent:
        return main_agent.get_status()
    return {"active_agents": []}


@app.get("/api/tasks")
async def get_tasks():
    open_tasks = await db.get_open_tasks()
    return [t.model_dump() for t in open_tasks]


@app.get("/api/status")
async def get_status():
    status = main_agent.get_status() if main_agent else {"active_agents": []}
    status["budget"] = {
        "used": budget_tracker.used,
        "budget": budget_tracker.daily_budget,
        "remaining": budget_tracker.remaining,
    }
    return status


@app.get("/api/budget")
async def get_budget():
    return {
        "used": budget_tracker.used,
        "budget": budget_tracker.daily_budget,
        "remaining": budget_tracker.remaining,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.frontend_port, reload=True)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_smart_integration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_smart_integration.py
git commit -m "refactor: slim main.py with MainAgent — no sim loop"
```

---

### Task 8: Update Frontend — Passive Dashboard

**Files:**
- Modify: `frontend/game.js`
- Modify: `frontend/agents.js`

- [ ] **Step 1: Simplify agents.js**

Replace `frontend/agents.js` with a passive version. Key changes:
- Remove idle FSM (TYPE, IDLE, WALK states)
- Remove BFS pathfinding
- Remove `isWalkable` function (fixes the name collision bug)
- Agents are either visible (working) or hidden (idle)

```javascript
// frontend/agents.js
// Passive agent display — agents appear when working, disappear when done

const AGENT_SPRITES = {
    coder: { key: 'adam', frame: 0 },
    researcher: { key: 'amelia', frame: 0 },
    writer: { key: 'bob', frame: 0 },
    ops: { key: 'alex', frame: 0 },
};

// Desk positions for each agent type (tile coords)
const DESK_POSITIONS = {
    coder: { x: 10, y: 20 },
    researcher: { x: 20, y: 25 },
    writer: { x: 25, y: 25 },
    ops: { x: 40, y: 15 },
};

// Main agent always visible
const MAIN_AGENT_POS = { x: 30, y: 10 };

class AgentDisplay {
    constructor(scene) {
        this.scene = scene;
        this.sprites = {};  // agent_id -> sprite
        this.bubbles = {};  // agent_id -> text object
        this.tileSize = 48;

        // Create main agent sprite (always visible)
        this._createMainAgent();
    }

    _createMainAgent() {
        const x = MAIN_AGENT_POS.x * this.tileSize + this.tileSize / 2;
        const y = MAIN_AGENT_POS.y * this.tileSize + this.tileSize / 2;
        this.mainSprite = this.scene.add.sprite(x, y, 'alex', 0);
        this.mainSprite.setDepth(10);
        this.mainLabel = this.scene.add.text(x, y - 30, '🧠 Falkenstein', {
            fontSize: '12px',
            color: '#ffffff',
            backgroundColor: '#333333',
            padding: { x: 4, y: 2 },
        }).setOrigin(0.5).setDepth(11);
    }

    spawnAgent(agentId, agentType, taskTitle) {
        const pos = DESK_POSITIONS[agentType] || DESK_POSITIONS.ops;
        const spriteInfo = AGENT_SPRITES[agentType] || AGENT_SPRITES.ops;
        const x = pos.x * this.tileSize + this.tileSize / 2;
        const y = pos.y * this.tileSize + this.tileSize / 2;

        // Create sprite
        const sprite = this.scene.add.sprite(x, y, spriteInfo.key, spriteInfo.frame);
        sprite.setDepth(10);
        sprite.setAlpha(0);
        this.scene.tweens.add({ targets: sprite, alpha: 1, duration: 500 });
        this.sprites[agentId] = sprite;

        // Create speech bubble
        const bubble = this.scene.add.text(x, y - 35, `💻 ${taskTitle}`, {
            fontSize: '10px',
            color: '#ffffff',
            backgroundColor: '#1a1a2e',
            padding: { x: 4, y: 2 },
            wordWrap: { width: 200 },
        }).setOrigin(0.5).setDepth(11);
        this.bubbles[agentId] = bubble;

        // Typing animation
        this._startTypingAnim(sprite);
    }

    removeAgent(agentId) {
        const sprite = this.sprites[agentId];
        const bubble = this.bubbles[agentId];
        if (sprite) {
            this.scene.tweens.add({
                targets: sprite,
                alpha: 0,
                duration: 500,
                onComplete: () => sprite.destroy(),
            });
            delete this.sprites[agentId];
        }
        if (bubble) {
            this.scene.tweens.add({
                targets: bubble,
                alpha: 0,
                duration: 500,
                onComplete: () => bubble.destroy(),
            });
            delete this.bubbles[agentId];
        }
    }

    updateBubble(agentId, text) {
        const bubble = this.bubbles[agentId];
        if (bubble) {
            bubble.setText(text);
        }
    }

    _startTypingAnim(sprite) {
        // Simple bobbing animation to indicate activity
        this.scene.tweens.add({
            targets: sprite,
            y: sprite.y - 3,
            duration: 600,
            yoyo: true,
            repeat: -1,
            ease: 'Sine.easeInOut',
        });
    }

    handleEvent(event) {
        switch (event.type) {
            case 'agent_spawned':
                this.spawnAgent(event.agent_id, event.agent_type, event.task);
                break;
            case 'agent_done':
                this.removeAgent(event.agent_id);
                break;
            case 'agent_working':
                this.updateBubble(event.agent_id, `💻 ${event.status || ''}`);
                break;
        }
    }
}
```

- [ ] **Step 2: Simplify game.js**

Key changes to `frontend/game.js`:
- Remove player character (WASD movement, camera follow)
- Remove collision grid building
- Remove `isWalkable` function
- Use `AgentDisplay` instead of `AgentSprites`
- Connect WebSocket to new event types
- Camera: static centered view or free-pan with mouse drag

Replace the WebSocket message handler section:

```javascript
// In the WebSocket onmessage handler, replace all event handling with:
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    switch (data.type) {
        case 'full_state':
            // Initialize active agents from state
            if (data.active_agents) {
                data.active_agents.forEach(a => {
                    agentDisplay.spawnAgent(a.agent_id, a.type, a.task);
                });
            }
            break;
        case 'state_update':
            // Sync active agents
            break;
        case 'agent_spawned':
        case 'agent_done':
        case 'agent_working':
            agentDisplay.handleEvent(data);
            break;
    }
};
```

Remove: player creation, player update loop, collision detection, shift-sprint, camera follow.
Keep: tilemap loading, camera setup (static/draggable), zoom controls.

- [ ] **Step 3: Test manually**

Start the server and open the frontend in a browser to verify:
- Tilemap renders correctly
- No console errors
- WebSocket connects
- Submitting a task (via Telegram or API) shows agent in the office

- [ ] **Step 4: Commit**

```bash
git add frontend/game.js frontend/agents.js
git commit -m "refactor: passive office dashboard — no sim loop, no player"
```

---

### Task 9: Clean Up Dead Code

**Files:**
- Delete: `backend/sim_engine.py`, `backend/pm_logic.py`, `backend/team_lead.py`, `backend/orchestrator.py`, `backend/notification_router.py`, `backend/agent_pool.py`
- Delete: `backend/personality.py`, `backend/relationships.py` (if they exist)
- Delete: Old test files that test deleted modules

- [ ] **Step 1: Verify no imports of deleted modules remain**

Run: `grep -r "from backend.sim_engine\|from backend.pm_logic\|from backend.team_lead\|from backend.orchestrator\|from backend.notification_router\|from backend.agent_pool\|from backend.personality\|from backend.relationships" backend/ --include="*.py"`

Expected: No matches (main.py was already rewritten in Task 7).

If matches found, fix them before proceeding.

- [ ] **Step 2: Delete files**

```bash
rm -f backend/sim_engine.py backend/pm_logic.py backend/team_lead.py
rm -f backend/orchestrator.py backend/notification_router.py backend/agent_pool.py
rm -f backend/personality.py backend/relationships.py
```

- [ ] **Step 3: Clean up old tests**

Delete test files that test the removed modules:

```bash
rm -f tests/test_integration_routing.py tests/test_obsidian_manager_routing.py
rm -f tests/test_pm_logic.py tests/test_team_lead.py tests/test_sub_agents.py
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All new tests pass. Old tests that reference deleted modules should already be deleted.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove sim engine, PM logic, orchestrator, and other dead code"
```

---

### Task 10: Update Config & CLAUDE.md

**Files:**
- Modify: `backend/config.py`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update config.py**

Add `LLM_BACKEND` and set `obsidian_auto_submit_tasks` default to `True`:

```python
# In Settings class, change:
obsidian_auto_submit_tasks: bool = True  # was False

# Add:
llm_backend: str = "ollama"  # ollama | gemini_cli | claude_cli
```

- [ ] **Step 2: Update CLAUDE.md**

Replace the content of `CLAUDE.md` to reflect the new architecture:

```markdown
# CLAUDE.md

Smart Assistant: 1 MainAgent + SubAgents on demand. Telegram = Steuerung, Obsidian = Wissensbasis, Büro-UI = passiver Monitor.

## Commands
\```bash
source venv/bin/activate && pip install -r requirements.txt  # setup
python -m backend.main                                        # server :8080
python -m pytest tests/ -v                                    # tests
\```
Requires: Python 3.11+, Ollama running, `ollama pull gemma4:26b`

## Stack
Frontend: Phaser.js 3.80 + Tiled (48px) passive dashboard | Backend: FastAPI + WebSockets + aiosqlite | LLM: Ollama (Gemma 4) | Premium: Gemini/Claude CLI | DB: SQLite | Config: pydantic-settings `.env`

## Architecture
- MainAgent (`main_agent.py`): Klassifiziert Input, antwortet direkt oder spawnt SubAgent
- SubAgents (`sub_agent.py`): Kurzlebig, fokussiertes Tool-Set (coder/researcher/writer/ops)
- ObsidianWriter (`obsidian_writer.py`): Kanban, Task-Notes, Ergebnis-Routing
- Telegram: Thin transport, alles durch MainAgent
- Frontend: Zeigt nur aktive Agents, kein Sim-Loop

## Konventionen
- SubAgent-Typen: `coder`, `researcher`, `writer`, `ops`
- Ergebnis-Ordner: `Recherchen`, `Guides`, `Cheat-Sheets`, `Code`, `Reports`
- Pfade via `.env`, keine hardcodierten Pfade
- Sprache: Doku/Kommunikation Deutsch, Code-Kommentare Englisch
- DB-Tabellen: `agents`, `tasks`, `messages`, `tool_log`

## Token-Effizienz
- Subagenten mit `model: "sonnet"` oder `model: "haiku"` starten wenn Opus aktiv
- Explore-Agents immer mit `model: "sonnet"`
- Antworten kurz und direkt, kein Filler
```

- [ ] **Step 3: Commit**

```bash
git add backend/config.py CLAUDE.md
git commit -m "chore: update config and CLAUDE.md for smart assistant architecture"
```

---

### Task 11: End-to-End Smoke Test

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 2: Start server and test manually**

```bash
python -m backend.main
```

Verify:
1. Server starts without errors on :8080
2. Frontend loads (tilemap visible, no console errors)
3. Send a Telegram message → MainAgent classifies and responds
4. Send a task → SubAgent spawns, result in Obsidian
5. Check Kanban.md → entries move through Backlog → In Progress → Done

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: smoke test fixes for smart assistant"
```
