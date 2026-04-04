import asyncio
import shlex
from pathlib import Path
from backend.tools.base import Tool, ToolResult

# Destructive commands that are always blocked
BLACKLIST_PATTERNS = [
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=", "shutdown", "reboot",
    ":(){ :|:& };:", "fork bomb", "> /dev/sda", "mv / ",
]


class ShellRunnerTool(Tool):
    name = "shell_runner"
    mutating = True  # shell commands can change state
    description = (
        "Shell-Befehle ausführen. Arbeitsverzeichnis ist der Workspace. "
        "Destruktive Befehle sind blockiert. Timeout: 5 Minuten."
    )

    def __init__(self, workspace_path: Path, timeout: int = 300):
        self.workspace = workspace_path.resolve()
        self.timeout = timeout

    def _is_blacklisted(self, command: str) -> bool:
        cmd_lower = command.lower().strip()
        for pattern in BLACKLIST_PATTERNS:
            if pattern in cmd_lower:
                return True
        return False

    async def execute(self, params: dict) -> ToolResult:
        command = params.get("command", "").strip()
        if not command:
            return ToolResult(success=False, output="Kein Befehl angegeben.")

        if self._is_blacklisted(command):
            return ToolResult(success=False, output=f"Befehl blockiert (Blacklist): {command}")

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
            output = stdout.decode("utf-8", errors="replace")
            errors = stderr.decode("utf-8", errors="replace")

            if proc.returncode == 0:
                return ToolResult(success=True, output=output[:5000] or "(kein Output)")
            else:
                combined = f"Exit code {proc.returncode}\n"
                if output:
                    combined += f"stdout:\n{output[:3000]}\n"
                if errors:
                    combined += f"stderr:\n{errors[:2000]}"
                return ToolResult(success=False, output=combined[:5000])

        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(success=False, output=f"Timeout nach {self.timeout}s: {command}")
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
            },
            "required": ["command"],
        }
