from __future__ import annotations

"""
OpsExecutor — Intelligent project ops tool with recipes, safety, and environment inspection.
Used by DynamicAgent runs and MainAgent's ops_command confirmation flow.
"""

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from backend.tools.base import Tool, ToolResult


@dataclass
class CommandPlan:
    description: str
    commands: list[str]
    needs_confirmation: bool = True
    risk_level: str = "medium"
    restart_after: bool = False


# Always blocked — no exceptions
SAFETY_BLOCKLIST = [
    "rm -rf /", "rm -rf /*", "rm -rf ~", "mkfs", "dd if=",
    "shutdown", "reboot", ":(){ :|:& };:", "> /dev/sda", "mv / ",
    "chmod -R 777 /", "chown -R", "launchctl unload",
    "networksetup", "csrutil", "nvram", "format c:",
]


class OpsExecutor(Tool):
    name = "ops_executor"
    mutating = True
    description = (
        "Intelligentes Ops-Tool für Projekt-Operationen: update, restart, logs, status. "
        "Erkennt Rezepte aus natürlicher Sprache, prüft Sicherheit, inspiziert die Umgebung."
    )

    # Pre-defined recipes for common operations
    OPS_RECIPES: dict[str, list[str]] = {
        "update": ["git pull", "pip install -r requirements.txt"],
        "restart": ["echo 'Restart: Run ./start.sh or systemctl restart falki'"],
        "logs": ["tail -n 50 logs/falki.log 2>/dev/null || echo 'Kein Log-File gefunden'"],
        "status": [
            "git log --oneline -5",
            "df -h .",
            "python3 --version",
        ],
    }

    # Natural language → recipe mapping hints
    _RECIPE_KEYWORDS: dict[str, list[str]] = {
        "update": ["update", "aktualisier", "pull", "upgrade"],
        "restart": ["restart", "neustart", "starte neu", "reboot server"],
        "logs": ["log", "logs", "protokoll"],
        "status": ["status", "info", "übersicht", "version"],
    }

    def __init__(self, project_root: Path | str | None = None, timeout: int = 120):
        self.project_root = Path(project_root) if project_root else Path(__file__).parent.parent.parent
        self.timeout = timeout

    def _is_safe_command(self, command: str) -> bool:
        """Check if a command is safe to execute."""
        cmd_lower = command.lower().strip()
        for pattern in SAFETY_BLOCKLIST:
            if pattern in cmd_lower:
                return False
        return True

    def detect_recipe(self, text: str) -> str | None:
        """Detect a recipe name from natural language input."""
        text_lower = text.lower()
        for recipe, keywords in self._RECIPE_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    return recipe
        return None

    async def inspect_environment(self) -> str:
        """Inspect the project environment to give LLM context."""
        checks = [
            ("ls", "ls -la"),
            ("start.sh", f"cat {self.project_root}/start.sh 2>/dev/null || echo 'No start.sh'"),
            ("git remote", "git remote -v 2>/dev/null || echo 'No git'"),
            ("python version", "python3 --version 2>/dev/null || python --version 2>/dev/null"),
            ("uname", "uname -a"),
        ]
        parts = []
        for label, cmd in checks:
            output = await self._run_shell(cmd, str(self.project_root))
            parts.append(f"--- {label} ---\n{output}")
        return "\n\n".join(parts)

    async def execute(self, params: dict) -> ToolResult:
        """Execute a single command or recipe."""
        command = params.get("command", "").strip()
        cwd = params.get("cwd", "").strip() or str(self.project_root)

        if not command:
            return ToolResult(success=False, output="Kein Befehl angegeben.")

        # Check for recipe
        recipe = self.detect_recipe(command)
        if recipe and recipe in self.OPS_RECIPES:
            results = []
            for cmd in self.OPS_RECIPES[recipe]:
                if not self._is_safe_command(cmd):
                    results.append(f"Blockiert: {cmd}")
                    continue
                output = await self._run_shell(cmd, cwd)
                results.append(f"$ {cmd}\n{output}")
            return ToolResult(success=True, output="\n\n".join(results))

        # Safety check
        if not self._is_safe_command(command):
            return ToolResult(success=False, output=f"Blockiert (Sicherheit): Befehl enthält gefährliches Pattern.")

        output = await self._run_shell(command, cwd)
        success = "Exit code" not in output
        return ToolResult(success=success, output=output)

    async def execute_plan(self, plan: CommandPlan) -> list[ToolResult]:
        """Execute all commands in a confirmed plan."""
        results = []
        for cmd in plan.commands:
            if not self._is_safe_command(cmd):
                results.append(ToolResult(success=False, output=f"Blockiert: {cmd}"))
                continue
            output = await self._run_shell(cmd, str(self.project_root))
            success = "Exit code" not in output
            results.append(ToolResult(success=success, output=output))
        return results

    async def _run_shell(self, command: str, cwd: str | None = None) -> str:
        """Run a shell command and return output."""
        work_dir = cwd or str(self.project_root)
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env={**os.environ},
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
            output = stdout.decode("utf-8", errors="replace")
            errors = stderr.decode("utf-8", errors="replace")

            if proc.returncode == 0:
                result = output[:8000] or "(kein Output)"
                if errors:
                    result += f"\nstderr: {errors[:2000]}"
                return result
            else:
                combined = f"Exit code {proc.returncode}\n"
                if output:
                    combined += f"{output[:4000]}\n"
                if errors:
                    combined += f"stderr: {errors[:3000]}"
                return combined[:8000]

        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return f"Timeout nach {self.timeout}s"
        except Exception as e:
            return f"Fehler: {e}"

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell-Befehl oder Ops-Rezept (update, restart, logs, status)",
                },
                "cwd": {
                    "type": "string",
                    "description": "Arbeitsverzeichnis (Standard: Projekt-Root)",
                },
            },
            "required": ["command"],
        }
