import asyncio
from ollama import chat as ollama_chat
from backend.config import settings


class LLMClient:
    def __init__(self):
        self.model = settings.ollama_model
        self.host = settings.ollama_host

    async def chat(self, system_prompt: str, messages: list[dict]) -> str:
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        response = await asyncio.to_thread(
            ollama_chat, model=self.model, messages=full_messages
        )
        return response["message"]["content"]

    async def chat_with_tools(
        self, system_prompt: str, messages: list[dict], tools: list[dict]
    ) -> dict:
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        response = await asyncio.to_thread(
            ollama_chat, model=self.model, messages=full_messages, tools=tools
        )
        return response["message"]

    async def generate_sim_action(
        self, agent_name: str, personality: str, nearby_agents: list[str]
    ) -> str:
        nearby = ", ".join(nearby_agents) if nearby_agents else "niemand"
        prompt = (
            f"Du bist {agent_name}, ein Büro-Mitarbeiter. "
            f"Deine Persönlichkeit: {personality}. "
            f"In deiner Nähe: {nearby}. "
            f"Du hast gerade nichts zu tun. Was machst du? "
            f"Antworte mit GENAU EINEM Wort: wander, talk, coffee, phone, sit"
        )
        return await self.chat(
            system_prompt="Du simulierst einen Büro-Mitarbeiter. Antworte immer mit genau einem Wort.",
            messages=[{"role": "user", "content": prompt}],
        )

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
        )
