"""Tests for TelegramAllowlist."""
import pytest
from backend.security.telegram_allowlist import TelegramAllowlist


OWNER = "111"
EXTRA1 = "222"
EXTRA2 = "333"
STRANGER = "999"


# ── Construction ─────────────────────────────────────────────────────────────

class TestConstruction:
    def test_owner_only(self):
        al = TelegramAllowlist(owner_chat_id=OWNER)
        assert al.is_allowed(OWNER)
        assert al.list_allowed() == [OWNER]

    def test_empty_csv(self):
        al = TelegramAllowlist(owner_chat_id=OWNER, allowed_ids_csv="")
        assert al.list_allowed() == [OWNER]

    def test_csv_with_extras(self):
        al = TelegramAllowlist(owner_chat_id=OWNER, allowed_ids_csv=f"{EXTRA1},{EXTRA2}")
        assert EXTRA1 in al.list_allowed()
        assert EXTRA2 in al.list_allowed()

    def test_csv_strips_whitespace(self):
        al = TelegramAllowlist(owner_chat_id=OWNER, allowed_ids_csv=f" {EXTRA1} , {EXTRA2} ")
        assert al.is_allowed(EXTRA1)
        assert al.is_allowed(EXTRA2)

    def test_csv_deduplicates_owner(self):
        """Owner in CSV should not appear twice in list_allowed."""
        al = TelegramAllowlist(owner_chat_id=OWNER, allowed_ids_csv=f"{OWNER},{EXTRA1}")
        result = al.list_allowed()
        assert result.count(OWNER) == 1
        assert EXTRA1 in result

    def test_csv_skips_empty_entries(self):
        al = TelegramAllowlist(owner_chat_id=OWNER, allowed_ids_csv=f"{EXTRA1},,{EXTRA2},")
        assert al.is_allowed(EXTRA1)
        assert al.is_allowed(EXTRA2)
        assert "" not in al.list_allowed()


# ── is_owner ─────────────────────────────────────────────────────────────────

class TestIsOwner:
    def test_owner_is_owner(self):
        al = TelegramAllowlist(owner_chat_id=OWNER)
        assert al.is_owner(OWNER) is True

    def test_extra_is_not_owner(self):
        al = TelegramAllowlist(owner_chat_id=OWNER, allowed_ids_csv=EXTRA1)
        assert al.is_owner(EXTRA1) is False

    def test_stranger_is_not_owner(self):
        al = TelegramAllowlist(owner_chat_id=OWNER)
        assert al.is_owner(STRANGER) is False


# ── is_allowed ────────────────────────────────────────────────────────────────

class TestIsAllowed:
    def test_owner_always_allowed(self):
        al = TelegramAllowlist(owner_chat_id=OWNER)
        assert al.is_allowed(OWNER) is True

    def test_extra_allowed(self):
        al = TelegramAllowlist(owner_chat_id=OWNER, allowed_ids_csv=EXTRA1)
        assert al.is_allowed(EXTRA1) is True

    def test_stranger_not_allowed(self):
        al = TelegramAllowlist(owner_chat_id=OWNER)
        assert al.is_allowed(STRANGER) is False

    def test_chat_id_coerced_to_str(self):
        al = TelegramAllowlist(owner_chat_id=OWNER)
        # Pass as int to test coercion
        assert al.is_allowed(int(OWNER)) is True


# ── add ───────────────────────────────────────────────────────────────────────

class TestAdd:
    def test_add_new_id(self):
        al = TelegramAllowlist(owner_chat_id=OWNER)
        al.add(EXTRA1)
        assert al.is_allowed(EXTRA1)

    def test_add_idempotent(self):
        al = TelegramAllowlist(owner_chat_id=OWNER)
        al.add(EXTRA1)
        al.add(EXTRA1)
        assert al.list_allowed().count(EXTRA1) == 1

    def test_add_owner_is_noop(self):
        """Adding the owner again should not create a duplicate."""
        al = TelegramAllowlist(owner_chat_id=OWNER)
        al.add(OWNER)
        assert al.list_allowed().count(OWNER) == 1

    def test_add_strips_whitespace(self):
        al = TelegramAllowlist(owner_chat_id=OWNER)
        al.add(f" {EXTRA1} ")
        assert al.is_allowed(EXTRA1)


# ── remove ────────────────────────────────────────────────────────────────────

class TestRemove:
    def test_remove_extra(self):
        al = TelegramAllowlist(owner_chat_id=OWNER, allowed_ids_csv=EXTRA1)
        al.remove(EXTRA1)
        assert not al.is_allowed(EXTRA1)

    def test_remove_nonexistent_is_noop(self):
        al = TelegramAllowlist(owner_chat_id=OWNER)
        al.remove(STRANGER)  # Should not raise

    def test_cannot_remove_owner(self):
        al = TelegramAllowlist(owner_chat_id=OWNER)
        with pytest.raises(ValueError, match="owner"):
            al.remove(OWNER)

    def test_owner_stays_allowed_after_failed_remove(self):
        al = TelegramAllowlist(owner_chat_id=OWNER)
        try:
            al.remove(OWNER)
        except ValueError:
            pass
        assert al.is_allowed(OWNER)


# ── list_allowed ──────────────────────────────────────────────────────────────

class TestListAllowed:
    def test_owner_first(self):
        al = TelegramAllowlist(owner_chat_id=OWNER, allowed_ids_csv=f"{EXTRA1},{EXTRA2}")
        result = al.list_allowed()
        assert result[0] == OWNER

    def test_returns_all(self):
        al = TelegramAllowlist(owner_chat_id=OWNER, allowed_ids_csv=f"{EXTRA1},{EXTRA2}")
        result = al.list_allowed()
        assert set(result) == {OWNER, EXTRA1, EXTRA2}

    def test_empty_allowlist_returns_owner(self):
        al = TelegramAllowlist(owner_chat_id=OWNER)
        assert al.list_allowed() == [OWNER]


# ── to_csv ────────────────────────────────────────────────────────────────────

class TestToCsv:
    def test_csv_excludes_owner(self):
        al = TelegramAllowlist(owner_chat_id=OWNER, allowed_ids_csv=f"{EXTRA1},{EXTRA2}")
        csv = al.to_csv()
        assert OWNER not in csv.split(",")
        assert EXTRA1 in csv.split(",")
        assert EXTRA2 in csv.split(",")

    def test_empty_csv_when_no_extras(self):
        al = TelegramAllowlist(owner_chat_id=OWNER)
        assert al.to_csv() == ""

    def test_roundtrip(self):
        """to_csv() output can reconstruct the same allowlist."""
        original = TelegramAllowlist(owner_chat_id=OWNER, allowed_ids_csv=f"{EXTRA1},{EXTRA2}")
        csv = original.to_csv()
        restored = TelegramAllowlist(owner_chat_id=OWNER, allowed_ids_csv=csv)
        assert set(restored.list_allowed()) == set(original.list_allowed())
