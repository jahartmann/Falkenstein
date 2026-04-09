import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from backend.mcp import installer


def test_install_root_under_home():
    assert "falkenstein" in str(installer.INSTALL_ROOT).lower()


def test_is_installed_false_if_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    assert installer.is_installed("nope", "bin_name") is False


def test_is_installed_true_if_binary_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    server_dir = tmp_path / "apple-mcp" / "node_modules" / ".bin"
    server_dir.mkdir(parents=True)
    (server_dir / "apple-mcp").touch()
    assert installer.is_installed("apple-mcp", "apple-mcp") is True


def test_resolve_binary_returns_path(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    server_dir = tmp_path / "srv" / "node_modules" / ".bin"
    server_dir.mkdir(parents=True)
    (server_dir / "srvbin").touch()
    p = installer.resolve_binary("srv", "srvbin")
    assert p is not None
    assert p.name == "srvbin"


def test_resolve_binary_returns_none_if_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    assert installer.resolve_binary("nope", "x") is None


@pytest.mark.asyncio
async def test_install_runs_npm(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    async def fake_exec(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"installed\n", b""))
        return proc
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    # Pre-create the binary so resolve_binary succeeds after "install"
    server_dir = tmp_path / "srv" / "node_modules" / ".bin"
    server_dir.mkdir(parents=True)
    (server_dir / "srvbin").touch()
    r = await installer.install("srv", "srv-package", "srvbin")
    assert r.success is True
    assert r.binary_path is not None


@pytest.mark.asyncio
async def test_install_npm_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    async def fake_exec(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"ENOENT\n"))
        return proc
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    r = await installer.install("srv", "bad-pkg", "srvbin")
    assert r.success is False
    assert "ENOENT" in r.stderr


@pytest.mark.asyncio
async def test_uninstall_removes_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    (tmp_path / "srv").mkdir()
    (tmp_path / "srv" / "marker.txt").write_text("x")
    ok = await installer.uninstall("srv")
    assert ok is True
    assert not (tmp_path / "srv").exists()
