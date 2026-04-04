import asyncio
import tempfile
from pathlib import Path
from backend.tools.base import Tool, ToolResult


class CodeExecutorTool(Tool):
    name = "code_executor"
    mutating = True  # executes code that can change files
    description = (
        "Python- oder Shell-Code in einer Sandbox ausführen. "
        "Code wird im Workspace-Verzeichnis ausgeführt mit Timeout. "
        "Sprachen: python, shell."
    )

    def __init__(self, workspace_path: Path, timeout: int = 60):
        self.workspace = workspace_path.resolve()
        self.timeout = timeout

    async def execute(self, params: dict) -> ToolResult:
        code = params.get("code", "").strip()
        language = params.get("language", "python").lower()

        if not code:
            return ToolResult(success=False, output="Kein Code angegeben.")

        if language == "python":
            return await self._run_python(code)
        elif language in ("shell", "bash", "sh"):
            return await self._run_shell(code)
        else:
            return ToolResult(success=False, output=f"Unbekannte Sprache: {language}")

    async def _run_python(self, code: str) -> ToolResult:
        # Write code to temp file and execute
        tmp = self.workspace / ".tmp_exec.py"
        try:
            tmp.write_text(code, encoding="utf-8")
            proc = await asyncio.create_subprocess_exec(
                "python3", str(tmp),
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
                return ToolResult(
                    success=False,
                    output=f"Python-Fehler (exit {proc.returncode}):\n{errors[:3000]}\n{output[:2000]}"
                )
        except asyncio.TimeoutError:
            return ToolResult(success=False, output=f"Python-Timeout nach {self.timeout}s")
        except Exception as e:
            return ToolResult(success=False, output=f"Ausführungsfehler: {e}")
        finally:
            tmp.unlink(missing_ok=True)

    async def _run_shell(self, code: str) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                code,
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
                return ToolResult(
                    success=False,
                    output=f"Shell-Fehler (exit {proc.returncode}):\n{errors[:3000]}\n{output[:2000]}"
                )
        except asyncio.TimeoutError:
            return ToolResult(success=False, output=f"Shell-Timeout nach {self.timeout}s")
        except Exception as e:
            return ToolResult(success=False, output=f"Ausführungsfehler: {e}")

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Der auszuführende Code",
                },
                "language": {
                    "type": "string",
                    "enum": ["python", "shell"],
                    "description": "Programmiersprache (default: python)",
                },
            },
            "required": ["code"],
        }
