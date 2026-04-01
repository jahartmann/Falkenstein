from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    workspace_path: Path = Path("./workspace")
    obsidian_vault_path: Path = Path.home() / "Obsidian"
    db_path: Path = Path("./data/falkenstein.db")
    frontend_port: int = 8080

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
