import asyncio
import hashlib
import re
from pathlib import Path

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

# Regex for unchecked checkbox items only
TODO_RE = re.compile(r"^- \[ \] (.+)$")


def _hash_line(line: str) -> str:
    """Return SHA256 hex digest for a single todo line."""
    return hashlib.sha256(line.encode()).hexdigest()


def _extract_project(file_path: Path) -> str | None:
    """Extract project name from path like .../Projekte/{name}/Tasks.md."""
    parts = file_path.parts
    try:
        idx = parts.index("Projekte")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return None


class ObsidianWatcher:
    """Monitors Obsidian vault markdown files for new unchecked todo items."""

    def __init__(self, vault_path: Path, router, debounce_seconds: float = 2.0):
        self.vault = vault_path.resolve()
        self.router = router
        self.debounce_seconds = debounce_seconds

        # Maps file path -> set of known todo line hashes
        self._known: dict[str, set[str]] = {}

        # Asyncio event loop reference, set during start()
        self._loop: asyncio.AbstractEventLoop | None = None

        # Pending debounce task
        self._debounce_task: asyncio.Task | None = None

        self._observer: Observer | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def watched_files(self) -> list[Path]:
        """Return list of all markdown files we actively watch."""
        files: list[Path] = []

        inbox = self.vault / "Management" / "Inbox.md"
        if inbox.exists():
            files.append(inbox)

        projekte_root = self.vault / "Falkenstein" / "Projekte"
        if projekte_root.exists():
            for tasks_file in sorted(projekte_root.glob("*/Tasks.md")):
                files.append(tasks_file)

        return files

    def scan_files(self) -> None:
        """Snapshot current todo lines so future detect_changes finds only NEW ones."""
        for path in self._all_candidate_files():
            self._known[str(path)] = self._read_todo_hashes(path)

    def detect_changes(self) -> list[dict]:
        """
        Re-read all candidate files and return newly added todo items.
        Updates internal snapshot so the same item is not returned twice.
        """
        results: list[dict] = []

        for path in self._all_candidate_files():
            key = str(path)
            current_lines = self._read_todo_lines(path)
            known_hashes = self._known.get(key, set())

            new_todos = []
            current_hashes: set[str] = set()
            for line in current_lines:
                h = _hash_line(line)
                current_hashes.add(h)
                if h not in known_hashes:
                    new_todos.append(line)

            # Replace: track current state, not cumulative history
            self._known[key] = current_hashes

            project = _extract_project(path)
            for line in new_todos:
                results.append(
                    {
                        "content": line,
                        "source_file": str(path),
                        "project": project,
                    }
                )

        return results

    async def start(self) -> None:
        """Scan files, start watchdog observer, run until cancelled."""
        self._loop = asyncio.get_running_loop()
        self.scan_files()

        handler = _VaultEventHandler(self)
        self._observer = Observer()

        mgmt_dir = self.vault / "Management"
        projekte_dir = self.vault / "Falkenstein" / "Projekte"

        if mgmt_dir.exists():
            self._observer.schedule(handler, str(mgmt_dir), recursive=False)
        if projekte_dir.exists():
            self._observer.schedule(handler, str(projekte_dir), recursive=True)

        self._observer.start()
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the watchdog observer without blocking the event loop."""
        if self._observer is not None and self._observer.is_alive():
            self._observer.stop()
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._observer.join)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _all_candidate_files(self) -> list[Path]:
        """Delegate to watched_files — kept for internal call-site compatibility."""
        return self.watched_files

    @staticmethod
    def _read_todo_lines(path: Path) -> list[str]:
        """Return list of unchecked todo line contents (the text after `- [ ] `)."""
        if not path.exists():
            return []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []
        lines = []
        for raw in text.splitlines():
            m = TODO_RE.match(raw)
            if m:
                lines.append(m.group(1))
        return lines

    @staticmethod
    def _read_todo_hashes(path: Path) -> set[str]:
        """Return set of SHA256 hashes for current unchecked todo lines."""
        return {_hash_line(line) for line in ObsidianWatcher._read_todo_lines(path)}

    # Called from watchdog thread — must not touch the event loop directly
    def _on_file_modified(self, file_path: str) -> None:
        """Bridge: schedule debounced processing on the asyncio event loop."""
        self._schedule_debounce()

    def _schedule_debounce(self) -> None:
        """Called from watchdog thread. Schedule (or reschedule) debounce."""
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._reset_debounce)

    def _reset_debounce(self) -> None:
        """Must be called on the event loop thread. Atomically cancel+reschedule."""
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.ensure_future(self._process_after_delay())

    async def _process_after_delay(self) -> None:
        """Wait debounce_seconds, then detect changes and route events."""
        try:
            await asyncio.sleep(self.debounce_seconds)
            changes = self.detect_changes()
            for change in changes:
                await self.router.route_event("todo_from_obsidian", change)
        except asyncio.CancelledError:
            pass


class _VaultEventHandler(FileSystemEventHandler):
    """Watchdog event handler that forwards relevant modifications to the watcher."""

    # Files we actively monitor
    _WATCHED_NAMES = {"Inbox.md", "Tasks.md"}

    def __init__(self, watcher: ObsidianWatcher):
        super().__init__()
        self._watcher = watcher

    def on_modified(self, event: FileModifiedEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.name in self._WATCHED_NAMES:
            self._watcher._on_file_modified(event.src_path)
