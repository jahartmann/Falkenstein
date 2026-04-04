import datetime
from pathlib import Path

import pytest

from backend.obsidian_writer import ObsidianWriter


@pytest.fixture
def tmp_vault(tmp_path):
    vault = tmp_path / "TestVault"
    vault.mkdir()
    return vault


@pytest.fixture
def writer(tmp_vault):
    return ObsidianWriter(vault_path=tmp_vault)


def test_ensure_structure(writer, tmp_vault):
    writer.ensure_structure()
    assert (tmp_vault / "KI-Büro" / "Wissen").is_dir()
    assert (tmp_vault / "KI-Büro" / "Projekte").is_dir()
    assert (tmp_vault / "KI-Büro" / "Reports").is_dir()


def test_write_result_to_wissen(writer, tmp_vault):
    path = writer.write_result(
        title="Docker vs Podman",
        typ="recherche",
        content="# Docker vs Podman\n\nDocker ist...",
    )
    assert "Wissen" in str(path)
    assert path.exists()
    content = path.read_text()
    assert "typ: recherche" in content
    assert "Docker ist" in content


def test_write_result_guide(writer, tmp_vault):
    path = writer.write_result(
        title="Git Rebase Guide",
        typ="guide",
        content="# Git Rebase\n\nSchritt 1...",
    )
    assert "Wissen" in str(path)
    content = path.read_text()
    assert "typ: guide" in content


def test_write_result_with_project(writer, tmp_vault):
    path = writer.write_result(
        title="SEO Analyse",
        typ="recherche",
        content="# SEO\n\nErgebnis...",
        project="website",
    )
    assert "Projekte/website" in str(path)
    assert "Ergebnisse" not in str(path)
    assert path.exists()
    content = path.read_text()
    assert "typ: recherche" in content
    assert "Ergebnis..." in content


def test_write_result_without_project(writer, tmp_vault):
    path = writer.write_result(
        title="Allgemeine Recherche",
        typ="report",
        content="# Report\n\nInhalt...",
    )
    assert "KI-Büro/Wissen" in str(path)
    assert "Projekte" not in str(path)
    assert path.exists()


def test_write_report_creates_new(writer, tmp_vault):
    path = writer.write_report("Agent coder finished task X.")
    assert "Reports" in str(path)
    assert path.exists()
    content = path.read_text()
    assert "# Report" in content
    assert "Agent coder finished task X." in content


def test_write_report_appends(writer, tmp_vault):
    path1 = writer.write_report("First entry.")
    path2 = writer.write_report("Second entry.")
    assert path1 == path2
    content = path2.read_text()
    assert "First entry." in content
    assert "---" in content
    assert "Second entry." in content


def test_slugify():
    assert ObsidianWriter._slugify("Hello World!") == "hello-world"
    assert len(ObsidianWriter._slugify("a" * 100)) <= 60
