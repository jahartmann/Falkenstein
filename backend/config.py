from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "gemma4:26b"
    # Light model for simple decisions (sim actions, chat). Falls back to ollama_model.
    ollama_model_light: str = ""
    # Heavy model for complex tasks (tool use, reasoning). Falls back to ollama_model.
    ollama_model_heavy: str = ""
    workspace_path: Path = Path("./workspace")
    obsidian_vault_path: Path = Path.home() / "Obsidian"
    db_path: Path = Path("./data/falkenstein.db")
    frontend_port: int = 8080
    # Max retries for local LLM before escalating to premium CLI
    llm_max_retries: int = 3
    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # CLI Bridge
    cli_daily_token_budget: int = 50000
    cli_provider: str = "claude"  # claude or gemini
    # Ollama context window (default 32K, max 256K for gemma4:26b)
    ollama_num_ctx: int = 32768
    # Extended context for long tasks (Telegram history, repo loading)
    ollama_num_ctx_extended: int = 131072
    # Obsidian
    obsidian_watch_enabled: bool = True
    obsidian_auto_submit_tasks: bool = True

    @property
    def model_light(self) -> str:
        return self.ollama_model_light or self.ollama_model

    @property
    def model_heavy(self) -> str:
        return self.ollama_model_heavy or self.ollama_model

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
