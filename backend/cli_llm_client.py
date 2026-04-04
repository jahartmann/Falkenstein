"""
CLILLMClient — same interface as LLMClient, but uses Claude/Gemini CLI as backend.
Supports chat() and chat_with_tools() by passing tool schemas in the prompt
and parsing JSON tool calls from the response.
"""

import asyncio
import json
import os


class CLILLMClient:
    """LLM client that uses Claude or Gemini CLI as the backend."""

    def __init__(self, provider: str = "claude", timeout: int = 120):
        self.provider = provider  # "claude" or "gemini"
        self.timeout = timeout

    async def _call_cli(self, system_prompt: str, messages: list[dict],
                        timeout: int | None = None) -> str:
        """Call CLI and return raw text response."""
        # Build the full prompt from messages
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                parts.append(f"User: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content}")
            elif role == "tool":
                parts.append(f"Tool-Ergebnis: {content}")

        full_prompt = f"{system_prompt}\n\n{''.join(parts[-1:])}" if len(parts) == 1 else \
                      f"{system_prompt}\n\nGesprächsverlauf:\n" + "\n".join(parts)

        if self.provider == "claude":
            cmd = ["claude", "--bare", "-p", full_prompt, "--output-format", "json"]
        else:
            cmd = ["gemini", "-p", full_prompt]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ},
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout or self.timeout
            )
            output = stdout.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="replace")
                return f"CLI-Fehler: {err[:500]}"

            # Parse JSON response from Claude
            if self.provider == "claude":
                try:
                    data = json.loads(output)
                    return data.get("result", output)
                except json.JSONDecodeError:
                    return output

            return output.strip()

        except asyncio.TimeoutError:
            return f"CLI-Timeout nach {timeout or self.timeout}s"
        except FileNotFoundError:
            return f"CLI '{self.provider}' nicht gefunden. Ist es installiert?"
        except Exception as e:
            return f"CLI-Fehler: {e}"

    async def chat(self, system_prompt: str, messages: list[dict],
                   model: str | None = None, num_predict: int | None = None,
                   temperature: float | None = None, think: bool = False,
                   format_schema: dict | None = None,
                   num_ctx: int | None = None) -> str:
        """Same interface as LLMClient.chat()."""
        return await self._call_cli(system_prompt, messages)

    async def chat_with_tools(
        self, system_prompt: str, messages: list[dict], tools: list[dict],
        model: str | None = None, think: bool = False,
    ) -> dict:
        """Same interface as LLMClient.chat_with_tools().
        Passes tool schemas in the prompt and parses tool call JSON from response."""
        # Build tool description
        tool_desc_parts = ["Du hast folgende Tools zur Verfügung:\n"]
        for t in tools:
            func = t.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "")
            params = func.get("parameters", {})
            props = params.get("properties", {})
            required = params.get("required", [])

            param_lines = []
            for pname, pmeta in props.items():
                req = " (required)" if pname in required else ""
                param_lines.append(f"    - {pname}: {pmeta.get('description', pmeta.get('type', ''))}{req}")

            tool_desc_parts.append(f"Tool: {name}\n  Beschreibung: {desc}")
            if param_lines:
                tool_desc_parts.append("  Parameter:\n" + "\n".join(param_lines))
            tool_desc_parts.append("")

        tool_desc_parts.append(
            "Wenn du ein Tool nutzen willst, antworte mit JSON:\n"
            '{"tool_calls": [{"function": {"name": "<tool_name>", "arguments": {<args>}}}], "content": ""}\n\n'
            "Wenn du KEIN Tool brauchst und fertig bist, antworte mit normalem Text (kein JSON).\n"
            "Nutze immer nur EIN Tool pro Antwort."
        )

        enhanced_system = system_prompt + "\n\n" + "\n".join(tool_desc_parts)
        response = await self._call_cli(enhanced_system, messages)

        # Try to parse as tool call JSON
        text = response.strip()
        try:
            # Find JSON in response
            if "{" in text:
                json_str = text[text.index("{"):text.rindex("}") + 1]
                data = json.loads(json_str)
                if "tool_calls" in data:
                    return {
                        "content": data.get("content", ""),
                        "tool_calls": data["tool_calls"],
                    }
        except (json.JSONDecodeError, ValueError):
            pass

        # No tool calls — just content
        return {"content": text}
