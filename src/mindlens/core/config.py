"""MindLens configuration — loads .env and resolves vault paths."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    # LLM
    llm_provider: str = "openrouter"
    llm_model: str = "Xiaomi/MiMo-V2.5-Pro"
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"

    # OpenRouter Management
    openrouter_management_key: str = ""

    # Telegram
    telegram_token: str = ""
    telegram_user_id: int = 0

    # Vault
    vault_path: Path = field(default_factory=lambda: Path.home() / "mindlens")

    # Runtime
    env: str = "development"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> Config:
        """Load config from .env file."""
        if env_path:
            load_dotenv(env_path)
        else:
            # Try vault path first, then cwd
            for candidate in [
                Path(os.environ.get("MINDLENS_VAULT_PATH", "")) / ".env",
                Path.cwd() / ".env",
            ]:
                if candidate.exists():
                    load_dotenv(candidate)
                    break

        vault = Path(os.environ.get("MINDLENS_VAULT_PATH", str(Path.home() / "mindlens")))

        return cls(
            llm_provider=os.environ.get("MINDLENS_LLM_PROVIDER", "openrouter"),
            llm_model=os.environ.get("MINDLENS_LLM_MODEL", "Xiaomi/MiMo-V2.5-Pro"),
            llm_api_key=os.environ.get("MINDLENS_LLM_API_KEY", ""),
            llm_base_url=os.environ.get("MINDLENS_LLM_BASE_URL", "https://openrouter.ai/api/v1"),
            openrouter_management_key=os.environ.get("MINDLENS_OPENROUTER_MANAGEMENT_KEY", ""),
            telegram_token=os.environ.get("MINDLENS_TELEGRAM_TOKEN", ""),
            telegram_user_id=int(os.environ.get("MINDLENS_TELEGRAM_USER_ID", "0")),
            vault_path=vault,
            env=os.environ.get("MINDLENS_ENV", "development"),
            log_level=os.environ.get("MINDLENS_LOG_LEVEL", "INFO"),
        )

    def workspace_path(self, name: str) -> Path:
        """Get the vault path for a workspace."""
        return self.vault_path / name

    def workspace_db_path(self, name: str) -> Path:
        """Get the SQLite path for a workspace."""
        return self.vault_path / name / ".mindlens" / "workspace.db"

    def core_db_path(self) -> Path:
        """Get the core SQLite path."""
        return self.vault_path / ".mindlens" / "core.db"

    def global_skills_path(self) -> Path:
        """Get the global skills directory."""
        return self.vault_path / ".mindlens" / "skills"

    def global_instructions_path(self) -> Path:
        """Get the global instructions directory."""
        return self.vault_path / ".mindlens" / "instructions"

    def agents_path(self) -> Path:
        """Get the agent definitions directory (visible in Obsidian)."""
        return self.vault_path / "agents"

    def scheduled_tasks_path(self) -> Path:
        """Get the global scheduled tasks file (vault root)."""
        return self.vault_path / "tasks.yaml"

    def workspace_tasks_path(self, name: str) -> Path:
        """Get per-workspace tasks.yaml."""
        return self.vault_path / name / "tasks.yaml"
