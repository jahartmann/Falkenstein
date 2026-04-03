import asyncio
import json
import re
from ollama import chat as ollama_chat
from backend.config import settings

_THINK_RE = re.compile(r"<\|channel>thought.*?<channel\|>", re.DOTALL)


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
    def __init__(self):
        self.model = settings.ollama_model
        self.model_light = settings.model_light
        self.model_heavy = settings.model_heavy
        self.host = settings.ollama_host
        self.num_ctx = settings.ollama_num_ctx
        self.num_ctx_extended = settings.ollama_num_ctx_extended

    def _build_options(self, temperature: float | None = None) -> dict:
        """Build Ollama options. Note: num_predict and num_ctx removed —
        Gemma 4 via ollama 0.6+ returns empty with explicit num_predict."""
        opts = {}
        if temperature is not None:
            opts["temperature"] = temperature
        return opts or None

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

        response = await asyncio.to_thread(ollama_chat, **kwargs)
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
        response = await asyncio.to_thread(ollama_chat, **kwargs)
        msg = _get_message(response)
        if msg.get("content"):
            msg["content"] = strip_thinking(msg["content"])
        return msg

    async def generate_sim_action(
        self, agent_name: str, personality: str, nearby_agents: list[str]
    ) -> str:
        nearby = ", ".join(nearby_agents) if nearby_agents else "niemand"
        prompt = (
            f"Du bist {agent_name}, ein Büro-Mitarbeiter. "
            f"Persönlichkeit: {personality}. "
            f"In deiner Nähe: {nearby}. "
            f"Du hast gerade nichts zu tun. Was machst du? "
            f"Antworte mit GENAU EINEM Wort: wander, talk, coffee, phone, sit"
        )
        response = await self.chat(
            system_prompt="Du simulierst einen Büro-Mitarbeiter. Antworte immer mit genau einem Wort.",
            messages=[{"role": "user", "content": prompt}],
            model=self.model_light,
            num_predict=10,
            temperature=0.8,
        )
        action = response.strip().lower().rstrip(".")
        for valid in ["wander", "talk", "coffee", "phone", "sit"]:
            if valid in action:
                return valid
        return "sit"

    async def generate_chat_message(
        self, agent_name: str, personality: str, partner_name: str, topic: str | None = None
    ) -> str:
        prompt = (
            f"Du bist {agent_name} und redest gerade mit {partner_name} im Büro. "
            f"Deine Persönlichkeit: {personality}. "
        )
        if topic:
            prompt += f"Thema: {topic}. "
        prompt += "Sag etwas Kurzes und Natürliches (max 15 Wörter, auf Deutsch)."
        return await self.chat(
            system_prompt="Du bist ein Büro-Mitarbeiter in einer Simulation. Rede natürlich und kurz.",
            messages=[{"role": "user", "content": prompt}],
            model=self.model_light,
            num_predict=100,
            temperature=0.9,
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
        response = await asyncio.to_thread(ollama_chat, **kwargs)
        return _get_content(response)
