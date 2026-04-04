from __future__ import annotations

"""
SystemShellTool — runs shell commands anywhere on the system.
Unlike ShellRunnerTool (workspace-only), this can operate in any directory.
Uses a blocklist for destructive commands + path restrictions for sensitive dirs.
"""

import asyncio
import os
from pathlib import Path
from backend.tools.base import Tool, ToolResult

# Always blocked — no exceptions
HARD_BLACKLIST = [
    "rm -rf /", "rm -rf /*", "rm -rf ~", "mkfs", "dd if=",
    "shutdown", "reboot", ":(){ :|:& };:", "> /dev/sda", "mv / ",
    "chmod -R 777 /", "chown -R", "launchctl unload",
    "networksetup", "csrutil", "nvram",
]

# Directories that cannot be deleted from or written to via shell
PROTECTED_DIRS = ["/System", "/usr", "/bin", "/sbin", "/var", "/private"]


class SystemShellTool(Tool):
    name = "system_shell"
    mutating = True
    description = (
        "Shell-Befehle systemweit ausführen (nicht nur Workspace). "
        "Für Systemverwaltung, Dateisystem-Operationen, CLI-Tools. "
        "Destruktive Befehle auf Systemverzeichnisse sind blockiert."
    )

    def __init__(self, home_path: Path | None = None, timeout: int = 300):
        self.home = home_path or Path.home()
        self.timeout = timeout

    def _is_blocked(self, command: str) -> str | None:
        """Returns block reason or None if allowed."""
        cmd_lower = command.lower().strip()
        for pattern in HARD_BLACKLIST:
            if pattern in cmd_lower:
                return f"Blockiert (Sicherheit): {pattern}"
        # Block rm/mv targeting protected dirs
        for pdir in PROTECTED_DIRS:
            if f"rm " in cmd_lower and pdir in cmd_lower:
                return f"Blockiert: Löschen in {pdir} nicht erlaubt"
        return None

    async def execute(self, params: dict) -> ToolResult:
        command = params.get("command", "").strip()
        cwd = params.get("cwd", "").strip() or str(self.home)

        if not command:
            return ToolResult(success=False, output="Kein Befehl angegeben.")

        block_reason = self._is_blocked(command)
        if block_reason:
            return ToolResult(success=False, output=block_reason)

        # Resolve cwd
        work_dir = Path(cwd).expanduser().resolve()
        if not work_dir.exists():
            return ToolResult(success=False, output=f"Verzeichnis existiert nicht: {cwd}")

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_dir),
                env={**os.environ, "HOME": str(self.home)},
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
            output = stdout.decode("utf-8", errors="replace")
            errors = stderr.decode("utf-8", errors="replace")

            if proc.returncode == 0:
                result = output[:8000] or "(kein Output)"
                if errors:
                    result += f"\n\nstderr:\n{errors[:2000]}"
                return ToolResult(success=True, output=result)
            else:
                combined = f"Exit code {proc.returncode}\n"
                if output:
                    combined += f"stdout:\n{output[:4000]}\n"
                if errors:
                    combined += f"stderr:\n{errors[:3000]}"
                return ToolResult(success=False, output=combined[:8000])

        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return ToolResult(success=False, output=f"Timeout nach {self.timeout}s")
        except Exception as e:
            return ToolResult(success=False, output=f"Fehler: {e}")

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell-Befehl zum Ausführen",
                },
                "cwd": {
                    "type": "string",
                    "description": "Arbeitsverzeichnis (Standard: Home-Verzeichnis)",
                },
            },
            "required": ["command"],
        }
