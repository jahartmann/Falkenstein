from __future__ import annotations

import asyncio
import json
import re
import ollama as _ollama_lib
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_thinking(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


def _get_content(response) -> str:
    """Extract content from Ollama response (works with both dict and Pydantic object)."""
    try:
        return response.message.content or ""
    except AttributeError:
        return response["message"]["content"] or ""


def _get_message(response) -> dict:
    """Extract message as dict from Ollama response."""
    try:
        msg = response.message
        result = {"content": msg.content or ""}
        if msg.tool_calls:
            result["tool_calls"] = [
                {"function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        return result
    except AttributeError:
        return response["message"]


class LLMClient:
    def __init__(self, config: dict | None = None):
        if config:
            self.model = config.get("ollama_model", "gemma4:26b")
            self.model_light = config.get("ollama_model_light", "") or self.model
            self.model_heavy = config.get("ollama_model_heavy", "") or self.model
            self.host = config.get("ollama_host", "http://localhost:11434")
            self.num_ctx = int(config.get("ollama_num_ctx", "16384"))
            self.num_ctx_extended = int(config.get("ollama_num_ctx_extended", "32768"))
        else:
            # Fallback to legacy settings for backward compatibility
            from backend.config import settings
            self.model = settings.ollama_model
            self.model_light = settings.model_light
            self.model_heavy = settings.model_heavy
            self.host = settings.ollama_host
            self.num_ctx = settings.ollama_num_ctx
            self.num_ctx_extended = settings.ollama_num_ctx_extended

    def _ollama_chat(self, **kwargs):
        """Call ollama chat using the configured host."""
        return _ollama_lib.Client(host=self.host).chat(**kwargs)

    def _build_options(self, temperature: float | None = None,
                       num_ctx: int | None = None) -> dict:
        """Build Ollama options. Note: num_predict removed —
        Gemma 4 via ollama 0.6+ returns empty with explicit num_predict."""
        opts = {"num_ctx": num_ctx or self.num_ctx}
        if temperature is not None:
            opts["temperature"] = temperature
        return opts

    @staticmethod
    def _clean_history(messages: list[dict]) -> list[dict]:
        cleaned = []
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("content"):
                cleaned.append({**msg, "content": strip_thinking(msg["content"])})
            else:
                cleaned.append(msg)
        return cleaned

    async def chat(self, system_prompt: str, messages: list[dict],
                   model: str | None = None, num_predict: int | None = None,
                   temperature: float | None = None,
                   think: bool = False,
                   format_schema: dict | None = None,
                   num_ctx: int | None = None) -> str:
        full_messages = [{"role": "system", "content": system_prompt}]
        full_messages.extend(self._clean_history(messages))

        kwargs: dict = {
            "model": model or self.model,
            "messages": full_messages,
        }
        opts = self._build_options(temperature)
        if opts:
            kwargs["options"] = opts
        if format_schema is not None:
            kwargs["format"] = "json"

        response = await asyncio.to_thread(self._ollama_chat, **kwargs)
        return strip_thinking(_get_content(response))

    async def chat_with_tools(
        self, system_prompt: str, messages: list[dict], tools: list[dict],
        model: str | None = None, think: bool = False,
    ) -> dict:
        full_messages = [{"role": "system", "content": system_prompt}]
        full_messages.extend(self._clean_history(messages))

        kwargs = {
            "model": model or self.model_heavy,
            "messages": full_messages,
            "tools": tools,
        }
        opts = self._build_options(temperature=0.1)
        if opts:
            kwargs["options"] = opts
        response = await asyncio.to_thread(self._ollama_chat, **kwargs)
        msg = _get_message(response)
        if msg.get("content"):
            msg["content"] = strip_thinking(msg["content"])
        return msg

    async def chat_light(self, system_prompt: str = "", messages: list | None = None,
                         temperature: float = 0.7) -> str:
        """Chat using the light model (fast, reduced context)."""
        return await self.chat(
            system_prompt=system_prompt,
            messages=messages or [],
            model=self.model_light,
            num_ctx=max(4096, self.num_ctx // 4),
            temperature=temperature,
        )

    async def chat_heavy(self, system_prompt: str = "", messages: list | None = None,
                         temperature: float = 0.7) -> str:
        """Chat using the heavy model (full context, best reasoning)."""
        return await self.chat(
            system_prompt=system_prompt,
            messages=messages or [],
            model=self.model_heavy,
            num_ctx=self.num_ctx,
            temperature=temperature,
        )

    async def confidence_check(self, task_description: str, result: str) -> dict:
        prompt = (
            f"Bewerte dieses Arbeitsergebnis auf einer Skala von 0-10.\n\n"
            f"Aufgabe: {task_description[:500]}\n\n"
            f"Ergebnis: {result[:1500]}\n\n"
            f'Antworte NUR mit JSON: {{"score": <0-10>, "reason": "<kurze Begründung>"}}'
        )
        response = await self.chat(
            system_prompt="Du bist ein Code-Reviewer. Bewerte Qualität. Antworte nur mit JSON.",
            messages=[{"role": "user", "content": prompt}],
            model=self.model_light,
            num_predict=100,
            temperature=0.0,
            format_schema={"json": True},
        )
        try:
            text = response.strip()
            if "{" in text:
                text = text[text.index("{"):text.rindex("}") + 1]
            data = json.loads(text)
            return {"score": int(data.get("score", 5)), "reason": data.get("reason", "")}
        except (json.JSONDecodeError, ValueError):
            return {"score": 5, "reason": "Bewertung nicht parsebar"}

    async def chat_extended_context(self, system_prompt: str, messages: list[dict],
                                     model: str | None = None,
                                     num_predict: int | None = None,
                                     think: bool = False) -> str:
        return await self.chat(
            system_prompt=system_prompt, messages=messages,
            model=model, num_predict=num_predict, think=think,
            num_ctx=self.num_ctx_extended,
        )

    async def analyze_image(self, image_path: str, question: str,
                            model: str | None = None) -> str:
        messages = [{"role": "user", "content": question, "images": [image_path]}]
        kwargs = {
            "model": model or self.model_heavy,
            "messages": messages,
        }
        opts = self._build_options(temperature=0.2)
        if opts:
            kwargs["options"] = opts
        response = await asyncio.to_thread(self._ollama_chat, **kwargs)
        return _get_content(response)
