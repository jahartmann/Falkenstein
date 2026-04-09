"""Managed MCP server installation in ~/.falkenstein/mcp/."""
from __future__ import annotations
import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

INSTALL_ROOT = Path.home() / ".falkenstein" / "mcp"


@dataclass
class InstallResult:
    success: bool
    binary_path: Path | None
    error: str | None
    stderr: str


def server_dir(server_id: str) -> Path:
    return INSTALL_ROOT / server_id


def resolve_binary(server_id: str, bin_name: str) -> Path | None:
    """Return the absolute path of node_modules/.bin/<bin_name> if it exists."""
    p = server_dir(server_id) / "node_modules" / ".bin" / bin_name
    return p if p.exists() else None


def is_installed(server_id: str, bin_name: str) -> bool:
    """True iff the install dir exists AND the binary is resolvable."""
    return resolve_binary(server_id, bin_name) is not None


async def install(server_id: str, package: str, bin_name: str) -> InstallResult:
    """`npm install <package> --prefix ~/.falkenstein/mcp/<server_id>`."""
    target = server_dir(server_id)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return InstallResult(success=False, binary_path=None,
                             error=f"mkdir failed: {e}", stderr="")

    # Seed a minimal package.json so npm doesn't warn
    pkg_json = target / "package.json"
    if not pkg_json.exists():
        pkg_json.write_text(
            '{"name":"falkenstein-mcp-' + server_id + '","version":"0.0.0","private":true}\n'
        )

    log.info("Installing MCP %s (package=%s) into %s", server_id, package, target)
    stderr_text = ""
    try:
        proc = await asyncio.create_subprocess_exec(
            "npm", "install", package, "--prefix", str(target),
            "--no-audit", "--no-fund", "--loglevel=error",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
        if proc.returncode != 0:
            return InstallResult(
                success=False, binary_path=None,
                error=f"npm exited with code {proc.returncode}",
                stderr=stderr_text,
            )
    except FileNotFoundError:
        return InstallResult(success=False, binary_path=None,
                             error="npm not found on PATH", stderr="")
    except Exception as e:
        return InstallResult(success=False, binary_path=None,
                             error=f"npm invocation failed: {e}", stderr="")

    binary = resolve_binary(server_id, bin_name)
    if binary is None:
        return InstallResult(
            success=False, binary_path=None,
            error=f"Binary '{bin_name}' not found after install",
            stderr=stderr_text,
        )
    return InstallResult(success=True, binary_path=binary, error=None,
                         stderr=stderr_text)


async def uninstall(server_id: str) -> bool:
    """Remove the entire ~/.falkenstein/mcp/<server_id>/ directory."""
    target = server_dir(server_id)
    if not target.exists():
        return True
    try:
        await asyncio.to_thread(shutil.rmtree, target)
        return True
    except Exception as e:
        log.error("Uninstall of %s failed: %s", server_id, e)
        return False
