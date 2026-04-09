import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from backend.telegram_bot import TelegramBot


@pytest.fixture
def bot():
    return TelegramBot(token="test-token-123", chat_id="12345")


@pytest.fixture
def disabled_bot():
    return TelegramBot(token="", chat_id="")


def test_enabled(bot):
    assert bot.enabled


def test_disabled(disabled_bot):
    assert not disabled_bot.enabled


@pytest.mark.asyncio
async def test_send_message_disabled(disabled_bot):
    result = await disabled_bot.send_message("test")
    assert result is False


@pytest.mark.asyncio
async def test_send_message_success(bot):
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("backend.telegram_bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await bot.send_message("Hello!")
        assert result is True
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "Hello!" in str(call_args)


@pytest.mark.asyncio
async def test_send_message_failure(bot):
    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch("backend.telegram_bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await bot.send_message("Hello!")
        assert result is False


@pytest.mark.asyncio
async def test_poll_disabled(disabled_bot):
    messages = await disabled_bot.poll_updates()
    assert messages == []


@pytest.mark.asyncio
async def test_poll_updates_parses_messages(bot):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": [
            {
                "update_id": 100,
                "message": {
                    "text": "Build the API",
                    "chat": {"id": 12345},
                    "from": {"first_name": "Janik"},
                },
            }
        ]
    }

    with patch("backend.telegram_bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        messages = await bot.poll_updates()
        assert len(messages) == 1
        assert messages[0]["text"] == "Build the API"
        assert messages[0]["from"] == "Janik"
        assert bot._offset == 101


def test_on_message_handler(bot):
    handler = AsyncMock()
    bot.on_message(handler)
    assert handler in bot._handlers


@pytest.mark.asyncio
async def test_send_approval_request_builds_inline_keyboard():
    from backend.mcp.approvals import PendingApproval
    bot = TelegramBot(token="x", chat_id="123")
    with patch.object(bot, "_api_post", new=AsyncMock(return_value={"ok": True})) as mock:
        approval = PendingApproval(
            id="abc", server_id="apple-mcp", tool_name="send_message",
            args={"to": "+49"}, crew_id=None, chat_id=None,
            created_at=0.0,
        )
        await bot.send_approval_request(approval)
        mock.assert_awaited_once()
        args, kwargs = mock.call_args
        # Payload could be args[1] or a named kwarg — handle both
        payload = args[1] if len(args) > 1 else kwargs.get("payload", kwargs.get("json", args[-1] if args else {}))
        assert "reply_markup" in payload
        buttons = payload["reply_markup"]["inline_keyboard"][0]
        labels = [b["text"] for b in buttons]
        assert any("allow" in l.lower() for l in labels)
        assert any("deny" in l.lower() for l in labels)
        cb_data = [b["callback_data"] for b in buttons]
        assert any("approval:abc:allow" in c for c in cb_data)
        assert any("approval:abc:deny" in c for c in cb_data)


@pytest.mark.asyncio
async def test_callback_query_routes_to_approval_store():
    bot = TelegramBot(token="x", chat_id="123")
    resolved = []

    class FakeStore:
        def resolve(self, approval_id, decision, decided_by):
            resolved.append((approval_id, decision, decided_by))
            return True

    bot.approval_store = FakeStore()
    with patch.object(bot, "_api_post", new=AsyncMock(return_value={"ok": True})):
        await bot.handle_callback_query({
            "id": "q1",
            "from": {"id": 123},
            "data": "approval:abc:allow",
            "message": {"chat": {"id": 123}, "message_id": 42},
        })
    assert resolved == [("abc", "allow", "telegram")]
