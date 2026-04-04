import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from backend.tools.web_surfer import WebSurferTool


@pytest.fixture
def tool():
    return WebSurferTool(max_results=2, max_text_length=500)


MOCK_SEARCH_RESULTS = [
    {"title": "Test Result 1", "url": "https://example.com/1", "description": "First result snippet"},
    {"title": "Test Result 2", "url": "https://example.com/2", "description": "Second result snippet"},
]


@pytest.mark.asyncio
async def test_search_action(tool):
    with patch.object(tool, "_do_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS):
        result = await tool.execute({"action": "search", "query": "test query"})
    assert result.success
    assert "Test Result 1" in result.output
    assert "example.com/1" in result.output


@pytest.mark.asyncio
async def test_search_no_query(tool):
    result = await tool.execute({"action": "search"})
    assert not result.success
    assert "query" in result.output.lower()


@pytest.mark.asyncio
async def test_search_no_results(tool):
    with patch.object(tool, "_do_search", new_callable=AsyncMock, return_value=[]):
        result = await tool.execute({"action": "search", "query": "nothing"})
    assert not result.success


@pytest.mark.asyncio
async def test_scrape_action(tool):
    with patch.object(tool, "_do_scrape", return_value="Extracted page text here"):
        result = await tool.execute({"action": "scrape", "url": "https://example.com"})
    assert result.success
    assert "Extracted page text" in result.output


@pytest.mark.asyncio
async def test_scrape_no_url(tool):
    result = await tool.execute({"action": "scrape"})
    assert not result.success
    assert "url" in result.output.lower()


@pytest.mark.asyncio
async def test_scrape_empty_text(tool):
    with patch.object(tool, "_do_scrape", return_value=""):
        result = await tool.execute({"action": "scrape", "url": "https://example.com"})
    assert not result.success


@pytest.mark.asyncio
async def test_research_pipeline(tool):
    with patch.object(tool, "_do_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS), \
         patch.object(tool, "_do_scrape", return_value="Full page content from web"):
        result = await tool.execute({"action": "research", "query": "test"})
    assert result.success
    assert "Full page content" in result.output
    assert "Quellen:" in result.output


@pytest.mark.asyncio
async def test_research_scrape_fails_falls_back_to_snippets(tool):
    def fail_scrape(url):
        raise Exception("Connection timeout")

    with patch.object(tool, "_do_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS), \
         patch.object(tool, "_do_scrape", side_effect=fail_scrape):
        result = await tool.execute({"action": "research", "query": "test"})
    assert result.success
    assert "Snippets" in result.output or "snippet" in result.output.lower()


@pytest.mark.asyncio
async def test_unknown_action(tool):
    result = await tool.execute({"action": "unknown"})
    assert not result.success


@pytest.mark.asyncio
async def test_default_action_is_research(tool):
    with patch.object(tool, "_do_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS), \
         patch.object(tool, "_do_scrape", return_value="Page text"):
        result = await tool.execute({"query": "test"})
    assert result.success


@pytest.mark.asyncio
async def test_max_text_length_respected(tool):
    long_text = "x" * 2000
    with patch.object(tool, "_do_scrape", return_value=long_text):
        result = await tool.execute({"action": "scrape", "url": "https://example.com"})
    assert len(result.output) <= tool.max_text_length


def test_schema(tool):
    schema = tool.schema()
    assert schema["type"] == "object"
    assert "action" in schema["properties"]
    assert "query" in schema["properties"]
    assert "url" in schema["properties"]


def test_do_scrape_parses_html(tool):
    html = "<html><body><nav>Nav</nav><p>Main content here</p><script>evil()</script></body></html>"
    with patch("backend.tools.web_surfer.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client
        text = tool._do_scrape("https://example.com")
    assert "Main content here" in text
    assert "evil" not in text
    assert "Nav" not in text
