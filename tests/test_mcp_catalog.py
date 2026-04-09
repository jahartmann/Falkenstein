import pytest
from backend.mcp.catalog import CATALOG, validate_entry, REQUIRED_FIELDS


def test_catalog_has_expected_count():
    assert 10 <= len(CATALOG) <= 20


def test_catalog_contains_core_servers():
    for sid in ("apple-mcp", "mcp-obsidian", "desktop-commander",
                "filesystem", "brave-search", "github"):
        assert sid in CATALOG, f"missing catalog entry: {sid}"


def test_every_entry_has_required_fields():
    for sid, entry in CATALOG.items():
        for field in REQUIRED_FIELDS:
            assert field in entry, f"{sid} missing {field}"


def test_risk_levels_valid():
    for sid, entry in CATALOG.items():
        assert entry["risk_level"] in ("low", "medium", "high"), \
            f"{sid} has invalid risk_level"


def test_validate_entry_accepts_good_entry():
    validate_entry("x", {
        "name": "X", "description": "d", "package": "pkg", "bin": "b",
        "category": "c", "platform": [], "risk_level": "low",
        "requires_config": [], "permissions": {},
    })


def test_validate_entry_rejects_missing_field():
    with pytest.raises(ValueError, match="missing"):
        validate_entry("x", {"name": "X"})


def test_validate_entry_rejects_bad_risk():
    bad = {f: "" for f in REQUIRED_FIELDS}
    bad["platform"] = []
    bad["requires_config"] = []
    bad["permissions"] = {}
    bad["risk_level"] = "nuclear"
    with pytest.raises(ValueError, match="risk_level"):
        validate_entry("x", bad)
