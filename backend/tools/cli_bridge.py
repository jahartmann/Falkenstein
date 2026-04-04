import asyncio
import json
import datetime
from pathlib import Path
from backend.tools.base import Tool, ToolResult
from backend.config import settings


class CLIBudgetTracker:
    """Tracks daily CLI token usage against budget."""

    def __init__(self, daily_budget: int):
        self.daily_budget = daily_budget
        self._today: str = ""
        self._used: int = 0

    def _check_day(self):
        today = datetime.date.today().isoformat()
        if today != self._today:
            self._today = today
            self._used = 0

    @property
    def used(self) -> int:
        self._check_day()
        return self._used

    @property
    def remaining(self) -> int:
        return max(0, self.daily_budget - self.used)

    @property
    def over_budget(self) -> bool:
        return self.used >= self.daily_budget

    @property
    def warning_threshold(self) -> bool:
        """True if usage >= 80% of budget."""
        return self.used >= self.daily_budget * 0.8

    def record_usage(self, tokens: int):
        self._check_day()
        self._used += tokens


class CLIBridgeTool(Tool):
    name = "cli_bridge"
    description = (
        "Eskalation an Premium-CLI (Claude/Gemini) für komplexe Aufgaben. "
        "Nutzt CLI-Subprocess mit komprimiertem Prompt. "
        "Unterliegt täglichem Token-Budget."
    )

    def __init__(self, workspace_path: Path, budget_tracker: CLIBudgetTracker,
                 provider: str = "claude", timeout: int = 120):
        self.workspace = workspace_path.resolve()
        self.budget = budget_tracker
        self.provider = provider
        self.timeout = timeout

    async def execute(self, params: dict) -> ToolResult:
        prompt = params.get("prompt", "").strip()
        context = params.get("context", "")
        provider = params.get("provider", self.provider)

        if not prompt:
            return ToolResult(success=False, output="Kein Prompt angegeben.")

        if self.budget.over_budget:
            return ToolResult(
                success=False,
                output=f"Tägliches CLI-Token-Budget erschöpft ({self.budget.used:,}/{self.budget.daily_budget:,}). "
                       f"Warte bis morgen oder erhöhe CLI_DAILY_TOKEN_BUDGET."
            )

        # Build compressed prompt
        full_prompt = prompt
        if context:
            full_prompt = f"Kontext:\n{context[:2000]}\n\nAufgabe:\n{prompt}"

        if provider == "claude":
            return await self._call_claude(full_prompt)
        elif provider == "gemini":
            return await self._call_gemini(full_prompt)
        else:
            return ToolResult(success=False, output=f"Unbekannter Provider: {provider}")

    async def _call_claude(self, prompt: str) -> ToolResult:
        cmd = [
            "claude", "--bare", "-p", prompt,
            "--output-format", "json",
            "--max-turns", "5",
        ]
        return await self._run_cli(cmd, prompt, parse_json="claude")

    async def _call_gemini(self, prompt: str) -> ToolResult:
        cmd = ["gemini", "-p", prompt, "--output-format", "json"]
        return await self._run_cli(cmd, prompt, parse_json="gemini")

    async def _run_cli(self, cmd: list[str], prompt: str,
                       parse_json: str | None = None) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
            output = stdout.decode("utf-8", errors="replace")
            errors = stderr.decode("utf-8", errors="replace")

            # Try to extract real token count from JSON output
            result_text = output
            token_count = 0
            if parse_json and proc.returncode == 0:
                try:
                    data = json.loads(output)
                    if parse_json == "claude":
                        result_text = data.get("result", output)
                        usage = data.get("usage", {})
                        token_count = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
                    elif parse_json == "gemini":
                        result_text = data.get("response", output)
                        stats = data.get("stats", {}).get("tokens", {})
                        token_count = stats.get("input", 0) + stats.get("output", 0)
                except (json.JSONDecodeError, KeyError):
                    result_text = output

            # Fallback: estimate tokens if JSON parsing didn't yield a count
            if not token_count:
                token_count = (len(prompt) + len(result_text)) // 4
            self.budget.record_usage(token_count)

            if proc.returncode == 0:
                return ToolResult(success=True, output=result_text[:10000])
            else:
                return ToolResult(
                    success=False,
                    output=f"CLI-Fehler (exit {proc.returncode}):\n{errors[:3000]}\n{output[:2000]}"
                )
        except asyncio.TimeoutError:
            return ToolResult(success=False, output=f"CLI-Timeout nach {self.timeout}s")
        except FileNotFoundError:
            return ToolResult(
                success=False,
                output=f"CLI '{cmd[0]}' nicht gefunden. Ist es installiert und im PATH?"
            )
        except Exception as e:
            return ToolResult(success=False, output=f"CLI-Fehler: {e}")

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Die Aufgabe für die Premium-CLI",
                },
                "context": {
                    "type": "string",
                    "description": "Zusätzlicher Kontext (Code, bisheriger Entwurf)",
                },
                "provider": {
                    "type": "string",
                    "enum": ["claude", "gemini"],
                    "description": "CLI-Provider (default: claude)",
                },
            },
            "required": ["prompt"],
        }
