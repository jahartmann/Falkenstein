from __future__ import annotations

"""
OllamaManagerTool — manage Ollama models and server directly.
Actions: list, pull, remove, show, ps, status.
"""

import asyncio
import json
from backend.tools.base import Tool, ToolResult
from backend.config import settings


class OllamaManagerTool(Tool):
    name = "ollama_manager"
    mutating = True
    description = (
        "Ollama-Modelle verwalten: auflisten, herunterladen, entfernen, Details anzeigen, "
        "laufende Modelle prüfen. Actions: list, pull, remove, show, ps, status."
    )

    def __init__(self, timeout: int = 600):
        self.timeout = timeout

    async def _run_ollama(self, args: list[str], timeout: int | None = None) -> ToolResult:
        """Run an ollama CLI command."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ollama", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout or self.timeout
            )
            output = stdout.decode("utf-8", errors="replace")
            errors = stderr.decode("utf-8", errors="replace")

            if proc.returncode == 0:
                return ToolResult(success=True, output=output[:8000] or "(OK)")
            else:
                return ToolResult(
                    success=False,
                    output=f"ollama {' '.join(args)} fehlgeschlagen:\n{errors[:3000]}\n{output[:2000]}"
                )
        except asyncio.TimeoutError:
            return ToolResult(success=False, output=f"Timeout nach {timeout or self.timeout}s")
        except FileNotFoundError:
            return ToolResult(success=False, output="ollama nicht gefunden. Ist Ollama installiert?")
        except Exception as e:
            return ToolResult(success=False, output=f"Fehler: {e}")

    async def execute(self, params: dict) -> ToolResult:
        action = params.get("action", "").strip().lower()
        model = params.get("model", "").strip()

        if action == "list":
            return await self._run_ollama(["list"], timeout=10)

        elif action == "pull":
            if not model:
                return ToolResult(success=False, output="Kein Modell angegeben. Beispiel: gemma4:26b")
            return await self._run_ollama(["pull", model])

        elif action == "remove":
            if not model:
                return ToolResult(success=False, output="Kein Modell angegeben.")
            return await self._run_ollama(["rm", model], timeout=30)

        elif action == "show":
            if not model:
                model = settings.ollama_model
            return await self._run_ollama(["show", model], timeout=10)

        elif action == "ps":
            return await self._run_ollama(["ps"], timeout=10)

        elif action == "status":
            # Combined status: running models + loaded model info
            ps_result = await self._run_ollama(["ps"], timeout=10)
            list_result = await self._run_ollama(["list"], timeout=10)
            lines = [
                f"Konfiguriertes Modell: {settings.ollama_model}",
                f"Light-Modell: {settings.model_light}",
                f"Heavy-Modell: {settings.model_heavy}",
                "",
                "Laufende Modelle:",
                ps_result.output if ps_result.success else f"(Fehler: {ps_result.output})",
                "",
                "Installierte Modelle:",
                list_result.output if list_result.success else f"(Fehler: {list_result.output})",
            ]
            return ToolResult(success=True, output="\n".join(lines))

        else:
            return ToolResult(
                success=False,
                output=f"Unbekannte Action: {action}. Verfügbar: list, pull, remove, show, ps, status"
            )

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "pull", "remove", "show", "ps", "status"],
                    "description": "Aktion: list/pull/remove/show/ps/status",
                },
                "model": {
                    "type": "string",
                    "description": "Modellname (z.B. gemma4:26b, llama3.2:3b)",
                },
            },
            "required": ["action"],
        }
