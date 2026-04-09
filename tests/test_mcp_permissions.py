import pytest
from backend.mcp.permissions import classify_heuristic, PermissionResolver


def test_heuristic_safe_get():
    assert classify_heuristic("get_reminders") == "allow"


def test_heuristic_safe_list():
    assert classify_heuristic("list_notes") == "allow"


def test_heuristic_sensitive_create():
    assert classify_heuristic("create_reminder") == "ask"


def test_heuristic_sensitive_send():
    assert classify_heuristic("send_message") == "ask"


def test_heuristic_sensitive_play():
    assert classify_heuristic("play_music") == "ask"


def test_heuristic_unknown_defaults_to_ask():
    assert classify_heuristic("weirdfunc") == "ask"


def test_heuristic_case_insensitive():
    assert classify_heuristic("GetNotes") == "allow"
    assert classify_heuristic("SEND_Message") == "ask"


def test_heuristic_sensitive_wins_over_safe():
    # "send_get_info" should still be "ask" because send_ matches first
    assert classify_heuristic("send_get_info") == "ask"


@pytest.mark.asyncio
async def test_resolver_db_override_wins(tmp_path):
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    resolver = PermissionResolver(db)
    await resolver.set_override("apple-mcp", "create_reminder", "allow")
    assert await resolver.check("apple-mcp", "create_reminder") == "allow"
    await db.close()


@pytest.mark.asyncio
async def test_resolver_catalog_override(tmp_path):
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    resolver = PermissionResolver(db)
    # catalog sets play_music to "allow" for apple-mcp
    assert await resolver.check("apple-mcp", "play_music") == "allow"
    await db.close()


@pytest.mark.asyncio
async def test_resolver_heuristic_fallback(tmp_path):
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    resolver = PermissionResolver(db)
    assert await resolver.check("apple-mcp", "get_something_new") == "allow"
    assert await resolver.check("apple-mcp", "delete_something_new") == "ask"
    await db.close()


@pytest.mark.asyncio
async def test_resolver_reset_override(tmp_path):
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    resolver = PermissionResolver(db)
    await resolver.set_override("apple-mcp", "get_notes", "deny")
    assert await resolver.check("apple-mcp", "get_notes") == "deny"
    await resolver.clear_override("apple-mcp", "get_notes")
    assert await resolver.check("apple-mcp", "get_notes") == "allow"
    await db.close()
