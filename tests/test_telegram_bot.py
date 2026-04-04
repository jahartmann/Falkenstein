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
