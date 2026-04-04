from pathlib import Path
from backend.tools.base import Tool, ToolResult
from backend.llm_client import LLMClient


class VisionTool(Tool):
    name = "vision"
    description = (
        "Bilder und Screenshots analysieren mit Gemma 4 Vision. "
        "Kann Text in Bildern lesen, UI-Elemente erkennen, Fehler auf Screenshots finden."
    )

    def __init__(self, workspace_path: Path, llm: LLMClient):
        self.workspace = workspace_path.resolve()
        self.llm = llm

    def _resolve_safe(self, path_str: str) -> Path | None:
        target = (self.workspace / path_str).resolve()
        if not str(target).startswith(str(self.workspace)):
            return None
        return target

    async def execute(self, params: dict) -> ToolResult:
        image_path = params.get("image_path", "")
        question = params.get("question", "Was siehst du auf diesem Bild?")

        if not image_path:
            return ToolResult(success=False, output="Parameter 'image_path' fehlt.")

        target = self._resolve_safe(image_path)
        if target is None:
            return ToolResult(success=False, output="Pfad außerhalb des Workspace.")
        if not target.exists():
            return ToolResult(success=False, output=f"Bild nicht gefunden: {image_path}")
        if not target.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
            return ToolResult(success=False, output=f"Kein unterstütztes Bildformat: {target.suffix}")

        try:
            response = await self.llm.analyze_image(str(target), question)
            return ToolResult(success=True, output=response[:5000])
        except Exception as e:
            return ToolResult(success=False, output=f"Vision-Fehler: {e}")

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Relativer Pfad zum Bild im Workspace",
                },
                "question": {
                    "type": "string",
                    "description": "Frage zum Bild (default: 'Was siehst du auf diesem Bild?')",
                },
            },
            "required": ["image_path"],
        }
