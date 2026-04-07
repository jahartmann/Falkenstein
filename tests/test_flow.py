"""Tests for FalkensteinFlow — main entry point replacing MainAgent."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.flow.falkenstein_flow import FalkensteinFlow, CREW_CLASSES


def _make_deps():
    """Return a dict of minimal mock dependencies."""
    event_bus = MagicMock()
    native_ollama = MagicMock()
    native_ollama.quick_reply = AsyncMock(return_value="quick reply result")
    native_ollama.classify = AsyncMock(return_value={"crew_type": "coder"})
    vault_index = MagicMock()
    vault_index.as_context.return_value = "vault context"
    settings = MagicMock()
    settings.ollama_model = "gemma4:26b"
    settings.model_light = "gemma4:e4b"
    tools = {}
    return dict(
        event_bus=event_bus,
        native_ollama=native_ollama,
        vault_index=vault_index,
        settings=settings,
        tools=tools,
    )


def test_flow_can_be_created():
    """FalkensteinFlow(**deps) works without error."""
    deps = _make_deps()
    flow = FalkensteinFlow(**deps)
    assert flow is not None


def test_flow_has_crew_registry():
    """All 9 crew types present in crew_registry."""
    deps = _make_deps()
    flow = FalkensteinFlow(**deps)
    expected = {"coder", "researcher", "writer", "ops", "web_design", "swift", "ki_expert", "analyst", "premium"}
    assert expected == set(flow.crew_registry.keys())


@pytest.mark.asyncio
async def test_flow_quick_reply():
    """'Hallo!' triggers quick_reply path, calls native_ollama.quick_reply."""
    deps = _make_deps()
    flow = FalkensteinFlow(**deps)
    # Patch _run_crew to ensure it is NOT called for quick replies
    flow._run_crew = AsyncMock(return_value="should not be called")

    result = await flow.handle_message("Hallo!")

    deps["native_ollama"].quick_reply.assert_called_once()
    flow._run_crew.assert_not_called()
    assert result == "quick reply result"


@pytest.mark.asyncio
async def test_flow_routes_to_crew_by_keyword():
    """'Recherchiere X' keyword-matches to researcher crew."""
    deps = _make_deps()
    flow = FalkensteinFlow(**deps)
    flow._run_crew = AsyncMock(return_value="Done")

    result = await flow.handle_message("Recherchiere die neuesten KI-Tools")

    flow._run_crew.assert_called_once()
    crew_type_arg = flow._run_crew.call_args[0][0]
    assert crew_type_arg == "researcher"
    # classify should NOT be called — rule engine matched directly
    deps["native_ollama"].classify.assert_not_called()
    assert result == "Done"


@pytest.mark.asyncio
async def test_flow_classifies_when_no_keyword_match():
    """Ambiguous message falls through to classify, then runs the returned crew."""
    deps = _make_deps()
    deps["native_ollama"].classify = AsyncMock(return_value={"crew_type": "writer"})
    flow = FalkensteinFlow(**deps)
    flow._run_crew = AsyncMock(return_value="Done")

    # Message with no keyword that matches any crew directly
    result = await flow.handle_message("Bitte mach etwas Nützliches für mich")

    deps["native_ollama"].classify.assert_called_once()
    flow._run_crew.assert_called_once()
    crew_type_arg = flow._run_crew.call_args[0][0]
    assert crew_type_arg == "writer"
    assert result == "Done"
