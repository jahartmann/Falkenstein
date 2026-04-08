"""Async Ollama client for fast calls without CrewAI overhead."""

import json
import httpx

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "crew_type": {
            "type": "string",
            "enum": [
                "coder", "researcher", "writer", "ops",
                "web_design", "swift", "ki_expert", "analyst",
            ],
        },
        "task_description": {"type": "string"},
        "priority": {"type": "string", "enum": ["normal", "premium"]},
    },
    "required": ["crew_type", "task_description", "priority"],
}


class NativeOllamaClient:
    """Direct Ollama /api/chat client — bypasses CrewAI for speed."""

    def __init__(self, host: str, model_light: str, model_heavy: str,
                 keep_alive: str = "30m", timeout: float = 120.0):
        self.host = host.rstrip("/")
        self.model_light = model_light
        self.model_heavy = model_heavy
        self.keep_alive = keep_alive
        self.timeout = timeout

    async def classify(self, message: str) -> dict:
        """Classify a message into a crew_type using structured output."""
        crew_types = ", ".join(CLASSIFY_SCHEMA["properties"]["crew_type"]["enum"])
        system = (
            f"Classify the user message. Reply with ONLY a JSON object: "
            f'{{"crew_type": "<one of: {crew_types}>", '
            f'"task_description": "<brief>", "priority": "normal"}}'
        )
        raw = await self._chat(
            model=self.model_light,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
            think=False,  # Fast, no reasoning needed
        )
        # Parse JSON from response (may be wrapped in markdown)
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(text)

    async def quick_reply(self, message: str, context: str = "") -> str:
        """Fast direct reply without spawning a Crew."""
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": message})
        return await self._chat(model=self.model_light, messages=messages,
                                think=False)

    async def chat_with_tools(self, messages: list[dict], tools: list[dict],
                              model: str = "heavy") -> dict:
        """Single Ollama call with native tool definitions."""
        chosen = self.model_heavy if model == "heavy" else self.model_light
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            payload = {
                "model": chosen,
                "messages": messages,
                "tools": tools,
                "stream": False,
                "keep_alive": self.keep_alive,
            }
            r = await http.post(f"{self.host}/api/chat", json=payload)
            r.raise_for_status()
            return r.json()

    async def classify_mcp(self, message: str, available_tools: list[dict] | None = None) -> dict:
        """Classify a message as an MCP tool call. Returns {server_id, tool_name, args}."""
        tools_desc = ""
        if available_tools:
            tools_desc = "\n".join(
                f"- {t['server_id']}/{t['tool_name']}: {t.get('description', '')}"
                for t in available_tools
            )

        system_prompt = f"""Du bist ein Tool-Router. Analysiere die Nachricht und entscheide welches Tool aufgerufen werden soll.

Verfügbare Tools:
{tools_desc}

Antworte NUR mit einem JSON-Objekt:
{{"server_id": "...", "tool_name": "...", "args": {{...}}}}

Wenn kein Tool passt, antworte: {{"server_id": null, "tool_name": null, "args": {{}}}}"""

        try:
            response = await self._http.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model_light,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {"num_ctx": self.num_ctx},
                },
                timeout=30,
            )
            content = response.json()["message"]["content"]
            return json.loads(content)
        except (json.JSONDecodeError, KeyError, Exception):
            return {"server_id": None, "tool_name": None, "args": {}}

    async def _chat(self, model: str, messages: list[dict],
                    format: dict | None = None,
                    think: bool | None = None) -> str:
        """Low-level async Ollama chat call.

        Args:
            think: True = reasoning on, False = off (faster), None = model default.
                   NOTE: think=False + format= is bugged in Ollama (Issue #15260),
                   so we skip format when think is explicitly False.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            payload: dict = {
                "model": model,
                "messages": messages,
                "stream": False,
                "keep_alive": self.keep_alive,
            }
            if think is not None:
                payload["think"] = think
            # Ollama bug: think=False breaks format param (Issue #15260)
            if format is not None and think is not False:
                payload["format"] = format
            r = await http.post(f"{self.host}/api/chat", json=payload)
            r.raise_for_status()
            return r.json()["message"]["content"]
