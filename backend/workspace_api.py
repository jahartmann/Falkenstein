# backend/workspace_api.py
"""Workspace-Kontext-API — File-Upload und Verzeichnis-Pfad für Agenten-Kontext."""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

# In-memory session store: session_id → workspace info
_sessions: dict[str, dict] = {}
_DEFAULT_SESSION = "default"
_UPLOAD_BASE = Path(tempfile.gettempdir()) / "falkenstein_workspace"


class WorkspacePathRequest(BaseModel):
    path: str
    session_id: str = _DEFAULT_SESSION


@router.post("/path")
async def set_workspace_path(req: WorkspacePathRequest):
    """Set an existing local directory as workspace context (no upload)."""
    p = Path(req.path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Pfad nicht gefunden: {req.path}")

    ws_type = "directory" if p.is_dir() else "file"
    file_list: list[str] = []
    if p.is_dir():
        file_list = [
            str(f.relative_to(p))
            for f in p.rglob("*")
            if f.is_file() and not f.name.startswith(".")
        ][:100]

    _sessions[req.session_id] = {
        "path": str(p),
        "type": ws_type,
        "files": file_list,
        "active": True,
    }
    return {"path": str(p), "type": ws_type, "file_count": len(file_list)}


@router.post("/upload")
async def upload_workspace_file(
    file: UploadFile = File(...),
    session_id: str = _DEFAULT_SESSION,
):
    """Upload a file as workspace context."""
    upload_dir = _UPLOAD_BASE / session_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file.filename or "upload").name
    dest = upload_dir / safe_name
    content = await file.read()
    max_size = 10 * 1024 * 1024  # 10 MB
    if len(content) > max_size:
        raise HTTPException(status_code=413, detail=f"Datei zu groß (max 10 MB, erhalten: {len(content) // 1024 // 1024} MB)")
    dest.write_bytes(content)

    _sessions[session_id] = {
        "path": str(dest),
        "type": "file",
        "files": [file.filename or "upload"],
        "active": True,
    }
    return {"path": str(dest), "filename": file.filename, "size": len(content)}


@router.get("/current")
async def get_workspace(session_id: str = _DEFAULT_SESSION):
    """Get current workspace context for a session."""
    ws = _sessions.get(session_id)
    if not ws or not ws.get("active"):
        return {"active": False}
    return {**ws, "active": True}


@router.delete("/current")
async def clear_workspace(session_id: str = _DEFAULT_SESSION):
    """Clear workspace context for a session."""
    _sessions.pop(session_id, None)
    return {"status": "cleared"}


def get_workspace_context(session_id: str = _DEFAULT_SESSION) -> str:
    """Return workspace context string for injection into agent prompts."""
    ws = _sessions.get(session_id)
    if not ws or not ws.get("active"):
        return ""
    path = ws.get("path", "")
    files = ws.get("files", [])
    if files:
        file_preview = ", ".join(files[:10])
        return f"Aktiver Workspace: {path} ({len(files)} Dateien: {file_preview})"
    return f"Aktiver Workspace: {path}"
