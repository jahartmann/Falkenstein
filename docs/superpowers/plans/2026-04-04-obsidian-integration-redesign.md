# Obsidian-Integration Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vault-Struktur vereinfachen, Inbox-Einträge um `#typ @projekt` erweitern, Ergebnisse projektbasiert ablegen, Schedule-Vorlage bereitstellen.

**Architecture:** Watcher parst erweitertes Inbox-Format und reicht strukturierte Dicts durch. ObsidianWriter routet Ergebnisse ins Projekt oder in den globalen Ergebnisse-Ordner. Scheduler liest Schedules direkt unter `KI-Büro/Schedules/`.

**Tech Stack:** Python 3.11, FastAPI, Obsidian Vault (Markdown), pytest

---

### Task 1: Watcher — Inbox-Format `#typ @projekt` parsen

**Files:**
- Modify: `backend/obsidian_watcher.py:10` (TODO_RE)
- Modify: `backend/obsidian_watcher.py:96-103` (detect_changes dict)
- Modify: `backend/obsidian_watcher.py:56` (watched_files Inbox-Pfad)
- Modify: `backend/obsidian_watcher.py:115` (start() watch-Pfad)
- Modify: `backend/obsidian_watcher.py:190-192` (_process_after_delay callback)
- Test: `tests/test_obsidian_watcher.py`

- [ ] **Step 1: Write failing tests for new Inbox format**

Add to `tests/test_obsidian_watcher.py`:

```python
def test_parses_agent_type_from_inbox(vault, callback):
    watcher = make_watcher(vault, callback)
    watcher.scan_files()

    inbox = vault / "KI-Büro" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n"
        "- [ ] Recherchiere Ollama-Alternativen #researcher\n"
    )

    changes = watcher.detect_changes()
    assert len(changes) == 1
    assert changes[0]["agent_type"] == "researcher"
    assert "Recherchiere Ollama-Alternativen" in changes[0]["content"]


def test_parses_project_from_inbox(vault, callback):
    watcher = make_watcher(vault, callback)
    watcher.scan_files()

    inbox = vault / "KI-Büro" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n"
        "- [ ] Fix den Login-Bug #coder @website\n"
    )

    changes = watcher.detect_changes()
    assert len(changes) == 1
    assert changes[0]["agent_type"] == "coder"
    assert changes[0]["project"] == "website"
    assert "Fix den Login-Bug" in changes[0]["content"]


def test_parses_plain_inbox_todo(vault, callback):
    watcher = make_watcher(vault, callback)
    watcher.scan_files()

    inbox = vault / "KI-Büro" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n"
        "- [ ] Einfacher Task ohne Tags\n"
    )

    changes = watcher.detect_changes()
    assert len(changes) == 1
    assert changes[0]["agent_type"] is None
    assert changes[0]["project"] is None


def test_parses_only_project_tag(vault, callback):
    watcher = make_watcher(vault, callback)
    watcher.scan_files()

    inbox = vault / "KI-Büro" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n"
        "- [ ] Schreib Docs @falkenstein\n"
    )

    changes = watcher.detect_changes()
    assert len(changes) == 1
    assert changes[0]["agent_type"] is None
    assert changes[0]["project"] == "falkenstein"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_obsidian_watcher.py::test_parses_agent_type_from_inbox tests/test_obsidian_watcher.py::test_parses_project_from_inbox tests/test_obsidian_watcher.py::test_parses_plain_inbox_todo tests/test_obsidian_watcher.py::test_parses_only_project_tag -v`
Expected: FAIL — `agent_type` key missing, wrong Inbox path

- [ ] **Step 3: Update vault fixture for new structure**

In `tests/test_obsidian_watcher.py`, update the `vault` fixture:

```python
@pytest.fixture
def vault(tmp_path):
    """Create minimal vault structure."""
    ki = tmp_path / "KI-Büro"
    ki.mkdir(parents=True)
    (ki / "Inbox.md").write_text("# Inbox\n\n- [ ] [2026-04-01 10:00] Existing todo\n")

    proj = tmp_path / "KI-Büro" / "Projekte" / "website"
    proj.mkdir(parents=True)
    (proj / "Tasks.md").write_text("# Tasks — website\n\n- [ ] [2026-04-01 10:00] Old task\n")
    return tmp_path
```

- [ ] **Step 4: Update watcher — new regex, new paths, new dict keys**

In `backend/obsidian_watcher.py`:

1. Replace `TODO_RE` (line 10):
```python
# Match: - [ ] content #agent_type @project
# Groups: (1) content, (2) optional agent_type, (3) optional project
TODO_RE = re.compile(r"^- \[ \] (.+?)(?:\s+#(\w+))?(?:\s+@([\w-]+))?\s*$")
```

2. Update `watched_files` (lines 56-64):
```python
    @property
    def watched_files(self) -> list[Path]:
        """Return list of all markdown files we actively watch."""
        files: list[Path] = []

        inbox = self.vault / "KI-Büro" / "Inbox.md"
        if inbox.exists():
            files.append(inbox)

        projekte_root = self.vault / "KI-Büro" / "Projekte"
        if projekte_root.exists():
            for tasks_file in sorted(projekte_root.glob("*/Tasks.md")):
                files.append(tasks_file)

        return files
```

3. Update `_read_todo_lines` (lines 148-161) to return dicts:
```python
    @staticmethod
    def _read_todo_lines(path: Path) -> list[dict]:
        """Return list of parsed todo items as dicts."""
        if not path.exists():
            return []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []
        items = []
        for raw in text.splitlines():
            m = TODO_RE.match(raw)
            if m:
                items.append({
                    "raw": m.group(0),
                    "content": m.group(1).strip(),
                    "agent_type": m.group(2),
                    "project_tag": m.group(3),
                })
        return items
```

4. Update `_read_todo_hashes` (lines 163-166):
```python
    @staticmethod
    def _read_todo_hashes(path: Path) -> set[str]:
        """Return set of SHA256 hashes for current unchecked todo lines."""
        return {_hash_line(item["content"]) for item in ObsidianWatcher._read_todo_lines(path)}
```

5. Update `detect_changes` (lines 72-104):
```python
    def detect_changes(self) -> list[dict]:
        results: list[dict] = []

        for path in self._all_candidate_files():
            key = str(path)
            current_items = self._read_todo_lines(path)
            known_hashes = self._known.get(key, set())

            new_items = []
            current_hashes: set[str] = set()
            for item in current_items:
                h = _hash_line(item["content"])
                current_hashes.add(h)
                if h not in known_hashes:
                    new_items.append(item)

            self._known[key] = current_hashes

            project = _extract_project(path)
            for item in new_items:
                results.append({
                    "content": item["content"],
                    "source_file": str(path),
                    "project": item.get("project_tag") or project,
                    "agent_type": item.get("agent_type"),
                })

        return results
```

6. Update `start()` watch paths (lines 115-121):
```python
        inbox_dir = self.vault / "KI-Büro"
        projekte_dir = self.vault / "KI-Büro" / "Projekte"

        if inbox_dir.exists():
            self._observer.schedule(handler, str(inbox_dir), recursive=False)
        if projekte_dir.exists():
            self._observer.schedule(handler, str(projekte_dir), recursive=True)
```

7. Update `_process_after_delay` callback (lines 190-192):
```python
                if self._on_new_todo:
                    await self._on_new_todo(change)
```

- [ ] **Step 5: Update existing tests for new vault structure**

All existing tests reference `KI-Büro/Management/Inbox.md` — update to `KI-Büro/Inbox.md`. All tests reference `KI-Büro/Falkenstein/Projekte/` — update to `KI-Büro/Projekte/`.

Also update `test_debounce_calls_callback` — callback now receives a single dict arg:
```python
    callback.assert_awaited()
    args = callback.call_args[0]
    assert "Brand new todo" in args[0]["content"]
```

- [ ] **Step 6: Run all watcher tests**

Run: `python -m pytest tests/test_obsidian_watcher.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add backend/obsidian_watcher.py tests/test_obsidian_watcher.py
git commit -m "feat: watcher parses #typ @projekt from Inbox, new vault paths"
```

---

### Task 2: ObsidianWriter — Ergebnisse projektbasiert ablegen

**Files:**
- Modify: `backend/obsidian_writer.py:7-13` (remove _RESULT_TYPE_MAP)
- Modify: `backend/obsidian_writer.py:21-26` (paths)
- Modify: `backend/obsidian_writer.py:93-106` (remove_from_inbox path)
- Modify: `backend/obsidian_writer.py:108-117` (write_result)
- Test: `tests/test_obsidian_writer.py`

- [ ] **Step 1: Write failing tests for project-based results**

Add to `tests/test_obsidian_writer.py`:

```python
def test_write_result_with_project(writer, tmp_vault):
    proj = tmp_vault / "KI-Büro" / "Projekte" / "website"
    proj.mkdir(parents=True)

    path = writer.write_result(
        title="SEO Analyse",
        typ="recherche",
        content="# SEO\n\nErgebnis...",
        project="website",
    )
    assert "Projekte/website/Ergebnisse" in str(path)
    assert path.exists()
    content = path.read_text()
    assert "typ: recherche" in content
    assert "Ergebnis..." in content


def test_write_result_without_project(writer, tmp_vault):
    path = writer.write_result(
        title="Allgemeine Recherche",
        typ="report",
        content="# Report\n\nInhalt...",
    )
    assert "KI-Büro/Ergebnisse" in str(path)
    assert "Projekte" not in str(path)
    assert path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_obsidian_writer.py::test_write_result_with_project tests/test_obsidian_writer.py::test_write_result_without_project -v`
Expected: FAIL — `project` param not accepted, wrong paths

- [ ] **Step 3: Update fixture for new vault structure**

```python
@pytest.fixture
def tmp_vault(tmp_path):
    vault = tmp_path / "TestVault"
    vault.mkdir()
    ki = vault / "KI-Büro"
    ki.mkdir()
    kanban = ki / "Kanban.md"
    kanban.write_text(
        "# Kanban Board\n\n## Backlog\n\n## In Progress\n\n## Done\n\n## Archiv\n"
    )
    (ki / "Falkenstein" / "Tasks").mkdir(parents=True)
    (ki / "Ergebnisse").mkdir(parents=True)
    (ki / "Falkenstein" / "Daily Reports").mkdir(parents=True)
    # Inbox now directly under KI-Büro
    (ki / "Inbox.md").write_text("# Inbox\n\n")
    return vault
```

- [ ] **Step 4: Rewrite ObsidianWriter**

In `backend/obsidian_writer.py`:

```python
import datetime
import re
from pathlib import Path

VAULT_PREFIX = "KI-Büro"


class ObsidianWriter:
    """Manages Kanban board, task notes, and result files in Obsidian vault."""

    def __init__(self, vault_path: Path):
        self.vault = vault_path.resolve()
        self.kanban_path = self.vault / VAULT_PREFIX / "Kanban.md"
        self.inbox_path = self.vault / VAULT_PREFIX / "Inbox.md"
        self.tasks_dir = self.vault / VAULT_PREFIX / "Falkenstein" / "Tasks"
        self.results_dir = self.vault / VAULT_PREFIX / "Ergebnisse"
        self.projekte_dir = self.vault / VAULT_PREFIX / "Projekte"
        self.reports_dir = self.vault / VAULT_PREFIX / "Falkenstein" / "Daily Reports"

    @staticmethod
    def _slugify(title: str) -> str:
        slug = re.sub(r"[^\w\s-]", "", title.lower())
        return re.sub(r"\s+", "-", slug.strip())[:60]

    def create_task_note(self, title: str, typ: str, agent: str) -> Path:
        today = datetime.date.today().isoformat()
        slug = self._slugify(title)
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
        if not path.exists():
            return
        content = path.read_text(encoding="utf-8")
        content = re.sub(r"status: \w+", f"status: {status}", content, count=1)
        path.write_text(content, encoding="utf-8")

    def kanban_move(self, title: str, target_section: str):
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

        today = datetime.date.today().isoformat()
        slug = self._slugify(title)
        note_name = f"{today}-{slug}"

        checkbox = "[x]" if target_section == "done" else "[ ]"
        entry = f"- {checkbox} [[Tasks/{note_name}|{title}]]"

        entry_marker = f"[[Tasks/{note_name}|"
        lines = text.split("\n")
        lines = [l for l in lines if entry_marker not in l]
        text = "\n".join(lines)

        idx = text.find(target_header)
        if idx == -1:
            text += f"\n{target_header}\n{entry}\n"
        else:
            insert_pos = idx + len(target_header)
            text = text[:insert_pos] + f"\n{entry}" + text[insert_pos:]

        self.kanban_path.write_text(text, encoding="utf-8")

    def remove_from_inbox(self, text: str):
        """Remove or check off a matching todo from Inbox.md."""
        if not self.inbox_path.exists():
            return
        content = self.inbox_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        new_lines = []
        for line in lines:
            if line.strip().startswith("- [ ]") and text.strip() in line:
                continue
            new_lines.append(line)
        self.inbox_path.write_text("\n".join(new_lines), encoding="utf-8")

    def write_result(self, title: str, typ: str, content: str, project: str | None = None) -> Path:
        today = datetime.date.today().isoformat()
        slug = self._slugify(title)
        filename = f"{today}-{slug}.md"

        if project:
            path = self.projekte_dir / project / "Ergebnisse" / filename
        else:
            path = self.results_dir / filename

        path.parent.mkdir(parents=True, exist_ok=True)

        frontmatter = (
            f"---\n"
            f"typ: {typ}\n"
            f"erstellt: {today}\n"
            f"---\n\n"
        )
        path.write_text(frontmatter + content, encoding="utf-8")
        return path
```

- [ ] **Step 5: Update existing writer tests for new paths**

The Kanban tests reference `KI-Büro/Management/Kanban.md` — update fixture so `Kanban.md` is under `KI-Büro/` directly. Remove tests for `map_result_type` (method removed). Update `test_write_result_recherche` etc. to check for frontmatter `typ:` field instead of subdirectory name.

```python
def test_write_result_recherche(writer, tmp_vault):
    path = writer.write_result(
        title="Docker vs Podman",
        typ="recherche",
        content="# Docker vs Podman\n\nDocker ist...",
    )
    assert "Ergebnisse" in str(path)
    assert path.exists()
    content = path.read_text()
    assert "typ: recherche" in content
    assert "Docker ist" in content


def test_write_result_guide(writer, tmp_vault):
    path = writer.write_result(
        title="Git Rebase Guide",
        typ="guide",
        content="# Git Rebase\n\nSchritt 1...",
    )
    assert "Ergebnisse" in str(path)
    content = path.read_text()
    assert "typ: guide" in content
```

- [ ] **Step 6: Run all writer tests**

Run: `python -m pytest tests/test_obsidian_writer.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add backend/obsidian_writer.py tests/test_obsidian_writer.py
git commit -m "feat: project-based result routing, frontmatter typ field"
```

---

### Task 3: ObsidianManager — Vault-Struktur aktualisieren

**Files:**
- Modify: `backend/tools/obsidian_manager.py:10-34` (VAULT_STRUCTURE)
- Modify: `backend/tools/obsidian_manager.py:168` (_inbox path)
- Modify: `backend/tools/obsidian_manager.py:190` (_todo path)
- Modify: `backend/tools/obsidian_manager.py:201` (kanban path)
- Modify: `backend/tools/obsidian_manager.py:219-241` (_create_project)
- Modify: `backend/tools/obsidian_manager.py:248-258` (write_task_result)
- Test: `tests/test_obsidian_manager.py`

- [ ] **Step 1: Update VAULT_STRUCTURE constant**

In `backend/tools/obsidian_manager.py`, replace `VAULT_STRUCTURE` (lines 10-34):

```python
VAULT_STRUCTURE = {
    VAULT_PREFIX: {
        "Inbox.md": "# Inbox\n\nHier landen neue Aufgaben und Ideen.\n\n"
            "<!-- Format: - [ ] Beschreibung #agent-typ @projekt -->\n",
        "Kanban.md": (
            "# Kanban Board\n\n"
            "## Backlog\n\n## In Progress\n\n## Done\n\n## Archiv\n"
        ),
        "Schedules": {},
        "Projekte": {},
        "Ergebnisse": {},
        "Falkenstein": {
            "Tasks": {},
            "Daily Reports": {},
        },
    },
}
```

- [ ] **Step 2: Update internal paths**

Update `_inbox` method (line 168):
```python
        inbox_path = self.vault / VAULT_PREFIX / "Inbox.md"
```

Update `_todo` kanban path (line 201):
```python
            kanban_path = self.vault / VAULT_PREFIX / "Kanban.md"
```

Update `_create_project` (lines 219-241):
```python
    async def _create_project(self, name: str) -> ToolResult:
        if not name:
            return ToolResult(success=False, output="Projektname fehlt.")
        project_dir = self.vault / VAULT_PREFIX / "Projekte" / name
        if project_dir.exists():
            return ToolResult(success=True, output=f"Projekt '{name}' existiert bereits.")
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.date.today().isoformat()
            (project_dir / "README.md").write_text(
                f"# {name}\n\nErstellt: {today}\n\n## Beschreibung\n\n## Status\n\nIn Arbeit\n",
                encoding="utf-8",
            )
            (project_dir / "Tasks.md").write_text(
                f"# Tasks — {name}\n\n", encoding="utf-8",
            )
            (project_dir / "Ergebnisse").mkdir(exist_ok=True)
            return ToolResult(success=True, output=f"Projekt '{name}' angelegt mit README, Tasks, Ergebnisse.")
        except Exception as e:
            return ToolResult(success=False, output=str(e))
```

Update `_todo` project path (line 190):
```python
            todo_path = self.vault / VAULT_PREFIX / "Projekte" / project / "Tasks.md"
```

Update `write_task_result` (lines 248-258):
```python
    async def write_task_result(self, task_title: str, result: str,
                                project: str | None, agent_name: str) -> ToolResult:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        if project:
            path_str = f"{VAULT_PREFIX}/Projekte/{project}/Tasks.md"
            content = f"\n\n### {task_title} ✅\n*{agent_name}* — {timestamp}\n\n{result}"
            return await self._append(path_str, content)
        else:
            content = f"[DONE] {task_title} ({agent_name}): {result[:300]}"
            return await self._inbox(content)
```

- [ ] **Step 3: Update obsidian_manager tests**

Run: `python -m pytest tests/test_obsidian_manager.py -v` to see which tests break, then update paths accordingly.

- [ ] **Step 4: Run all manager tests**

Run: `python -m pytest tests/test_obsidian_manager.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tools/obsidian_manager.py tests/test_obsidian_manager.py
git commit -m "feat: obsidian_manager uses new flat vault structure"
```

---

### Task 4: Scheduler — Schedules-Pfad anpassen

**Files:**
- Modify: `backend/scheduler.py:213,221` (VAULT_PREFIX, schedules_dir)
- Test: `tests/test_scheduler.py` (if exists, update paths)

- [ ] **Step 1: Update Scheduler paths**

In `backend/scheduler.py`, update `Scheduler.__init__` (lines 219-223):

```python
    def __init__(self, vault_path: Path):
        self.vault = vault_path.resolve()
        self.schedules_dir = self.vault / "KI-Büro" / "Schedules"
        self._last_run_path = self.schedules_dir / ".last_run.json"
        self.tasks: dict[str, ScheduledTask] = {}
        self._on_task_due = None
        self._running = False
```

Remove the module-level `VAULT_PREFIX = "KI-Büro"` (line 213) — it's already defined elsewhere and was only used for the path.

- [ ] **Step 2: Run scheduler tests**

Run: `python -m pytest tests/ -k scheduler -v`
Expected: All PASS (or update fixture paths if needed)

- [ ] **Step 3: Commit**

```bash
git add backend/scheduler.py
git commit -m "feat: scheduler reads from KI-Büro/Schedules/ directly"
```

---

### Task 5: main.py + main_agent.py — Callback-Signatur anpassen

**Files:**
- Modify: `backend/main.py:63-65` (handle_obsidian_todo)
- Modify: `backend/main_agent.py:524` (handle_message signature)
- Modify: `backend/main_agent.py:701-703` (write_result calls)
- Modify: `backend/main_agent.py:756-759` (handle_scheduled write_result)

- [ ] **Step 1: Update handle_obsidian_todo in main.py**

In `backend/main.py`, replace `handle_obsidian_todo` (lines 63-65):

```python
async def handle_obsidian_todo(todo: dict):
    """New todo from Obsidian Inbox/Tasks -> MainAgent."""
    await main_agent.handle_message(
        todo["content"],
        agent_type_hint=todo.get("agent_type"),
        project_hint=todo.get("project"),
    )
```

- [ ] **Step 2: Update MainAgent.handle_message**

In `backend/main_agent.py`, update `handle_message` signature (line 524):

```python
    async def handle_message(self, text: str, chat_id: str = "",
                             agent_type_hint: str | None = None,
                             project_hint: str | None = None):
```

When `agent_type_hint` is set, skip classification and use it directly. Pass `project_hint` through to `_handle_action`/`_handle_content` so it reaches `write_result`.

At line 544-547, pass project through:
```python
        elif msg_type == "action":
            await self._handle_action(classification, text, chat_id, project=project_hint)
        elif msg_type == "content":
            await self._handle_content(classification, text, chat_id, project=project_hint)
```

- [ ] **Step 3: Update write_result calls to pass project**

In `_handle_content` (around line 701):
```python
            self.obsidian_writer.write_result(
                title=title, typ=result_type, content=result, project=project,
            )
```

In `handle_scheduled` (around line 756):
```python
        self.obsidian_writer.write_result(
            title=task.name, typ="report", content=result,
        )
```

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/main_agent.py
git commit -m "feat: pass agent_type and project hints from watcher to agent"
```

---

### Task 6: Schedule-Vorlage im Vault anlegen

**Files:**
- Create: Vault-Datei `KI-Büro/Schedules/_vorlage.md` (via ObsidianManager or direct)
- Modify: `backend/scheduler.py:227-244` (load_tasks ignores _vorlage.md)

- [ ] **Step 1: Update Scheduler to skip template files**

In `backend/scheduler.py`, update `load_tasks` (line 234):

```python
        for path in sorted(self.schedules_dir.glob("*.md")):
            if path.name.startswith("_"):
                continue  # skip templates
```

- [ ] **Step 2: Create template file on vault init**

In `backend/scheduler.py`, add method to `Scheduler`:

```python
    def _create_schedule_template(self):
        """Create _vorlage.md template if it doesn't exist."""
        tpl = self.schedules_dir / "_vorlage.md"
        if tpl.exists():
            return
        tpl.write_text(
            "---\n"
            "name: Name des Jobs\n"
            "schedule: täglich 09:00\n"
            "agent: researcher\n"
            "active: true\n"
            "active_hours: 08:00-22:00\n"
            "light_context: false\n"
            "---\n\n"
            "<!-- Schedule-Formate:\n"
            "  täglich HH:MM | stündlich | alle N Minuten | alle N Stunden\n"
            "  Mo-Fr HH:MM | montags HH:MM ... sonntags HH:MM\n"
            "  wöchentlich TAG HH:MM | cron: EXPR\n"
            "\n"
            "  Agent-Typen: coder | researcher | writer | ops\n"
            "-->\n\n"
            "Dein Prompt hier. Was soll der Agent tun?\n",
            encoding="utf-8",
        )
```

Call it from `load_tasks` after ensuring the dir exists:

```python
    def load_tasks(self):
        self.tasks.clear()
        if not self.schedules_dir.exists():
            self.schedules_dir.mkdir(parents=True, exist_ok=True)
        self._create_default_heartbeat()
        self._create_schedule_template()
        # ... rest
```

- [ ] **Step 3: Run scheduler tests**

Run: `python -m pytest tests/ -k scheduler -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add backend/scheduler.py
git commit -m "feat: schedule template _vorlage.md, skip templates in loader"
```

---

### Task 7: Inbox-Header mit Format-Referenz

**Files:**
- Modify: `backend/tools/obsidian_manager.py` (VAULT_STRUCTURE Inbox.md content — already done in Task 3)

- [ ] **Step 1: Verify Inbox template has format reference**

Check that `VAULT_STRUCTURE` in `obsidian_manager.py` creates `Inbox.md` with the comment:
```markdown
<!-- Format: - [ ] Beschreibung #agent-typ @projekt -->
```

This was already done in Task 3. Verify by running:

Run: `python -c "from backend.tools.obsidian_manager import VAULT_STRUCTURE; print(VAULT_STRUCTURE['KI-Büro']['Inbox.md'])"`
Expected: Output contains `<!-- Format:`

- [ ] **Step 2: Commit (if any changes needed)**

Already committed in Task 3 — skip if no changes.

---

### Task 8: Final integration test

**Files:**
- Test: all test files

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Manual smoke test**

Run: `python -m backend.main`
Check:
- Server starts without errors
- Scheduler loads tasks
- Watcher starts watching

- [ ] **Step 3: Final commit if needed**

```bash
git add -A
git commit -m "chore: integration fixes for obsidian redesign"
```
