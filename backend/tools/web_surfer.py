import asyncio
from bs4 import BeautifulSoup
import httpx
from backend.tools.base import Tool, ToolResult
from backend.config import settings


class WebSurferTool(Tool):
    name = "web_research"
    description = (
        "Web-Recherche: Suche im Internet und extrahiere Text von Webseiten. "
        "Actions: search (Brave-Suche), scrape (Text einer URL extrahieren), "
        "research (kombiniert: sucht, scrapt besten Treffer, gibt Zusammenfassung)."
    )

    BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, max_results: int = 3, max_text_length: int = 3000):
        self.max_results = max_results
        self.max_text_length = max_text_length

    async def execute(self, params: dict) -> ToolResult:
        action = params.get("action", "research")
        query = params.get("query", "")
        url = params.get("url", "")

        if action == "search":
            if not query:
                return ToolResult(success=False, output="Parameter 'query' fehlt.")
            return await self._search(query)
        elif action == "scrape":
            if not url:
                return ToolResult(success=False, output="Parameter 'url' fehlt.")
            return await self._scrape(url)
        elif action == "research":
            if not query:
                return ToolResult(success=False, output="Parameter 'query' fehlt.")
            return await self._research_pipeline(query)
        else:
            return ToolResult(success=False, output=f"Unbekannte Action: {action}")

    async def _search(self, query: str) -> ToolResult:
        try:
            results = await self._do_search(query)
            if not results:
                return ToolResult(success=False, output="Keine Suchergebnisse gefunden.")
            output_lines = []
            for r in results:
                output_lines.append(f"- {r['title']}\n  {r['url']}\n  {r['description']}")
            return ToolResult(success=True, output="\n".join(output_lines))
        except Exception as e:
            return ToolResult(success=False, output=f"Suchfehler: {e}")

    async def _do_search(self, query: str) -> list[dict]:
        api_key = settings.brave_api_key
        if not api_key:
            return []
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                self.BRAVE_URL,
                params={"q": query, "count": self.max_results},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": api_key,
                },
            )
            resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
            })
        return results

    async def _scrape(self, url: str) -> ToolResult:
        try:
            text = await asyncio.to_thread(self._do_scrape, url)
            if not text:
                return ToolResult(success=False, output="Kein Text extrahiert.")
            return ToolResult(success=True, output=text[:self.max_text_length])
        except Exception as e:
            return ToolResult(success=False, output=f"Scrape-Fehler: {e}")

    def _do_scrape(self, url: str) -> str:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 Falkenstein-Agent/1.0"})
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [line for line in text.splitlines() if line.strip()]
        return "\n".join(lines)

    async def _research_pipeline(self, query: str) -> ToolResult:
        # Single search call — reuse results for snippets and scraping
        results = await self._do_search(query)
        if not results:
            return ToolResult(success=False, output="Keine Suchergebnisse.")

        best_url = results[0]["url"]
        scrape_result = await self._scrape(best_url)

        snippets = "\n".join(f"- {r['description']}" for r in results)
        if scrape_result.success:
            output = (
                f"Quelle: {best_url}\n\n"
                f"--- Haupttext ---\n{scrape_result.output}\n\n"
                f"--- Weitere Treffer ---\n{snippets}\n\n"
                f"Quellen:\n" +
                "\n".join(f"[{r['title']}]({r['url']})" for r in results)
            )
        else:
            output = (
                f"Scraping fehlgeschlagen, aber Snippets verfügbar:\n\n"
                f"{snippets}\n\n"
                f"Quellen:\n" +
                "\n".join(f"[{r['title']}]({r['url']})" for r in results)
            )
        return ToolResult(success=True, output=output[:self.max_text_length * 2])

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["search", "scrape", "research"],
                    "description": "search=Websuche, scrape=URL-Text extrahieren, research=beides kombiniert",
                },
                "query": {
                    "type": "string",
                    "description": "Suchbegriff (für search/research)",
                },
                "url": {
                    "type": "string",
                    "description": "URL zum Scrapen (nur bei action=scrape)",
                },
            },
            "required": ["action"],
        }
