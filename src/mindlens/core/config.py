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
    def _find_vault(cls) -> Path:
        """Auto-discover vault by looking for AGENTS.md in known locations.
        
        Priority: env var > Proton Drive > iCloud > ~/mindlens > cwd
        Only matches directories that are NOT the git repo itself.
        """
        env_path = os.environ.get("MINDLENS_VAULT_PATH", "")
        candidates = [
            Path.home() / "Library" / "CloudStorage" / "ProtonDrive-kevjac91@proton.me-folder" / "mindlens",
            Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "mindlens",
            Path.home() / "mindlens",
            Path.home() / "Documents" / "mindlens",
        ]
        # If env var is set, try it first
        if env_path:
            candidates.insert(0, Path(env_path))

        for p in candidates:
            if p and p.exists() and (p / "AGENTS.md").exists():
                return p
        return Path.home() / "mindlens"

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> Config:
        """Load config from .env file. Auto-discovers vault if not set."""
        vault = cls._find_vault()

        # Load .env from vault (single source of truth)
        vault_env = vault / ".env"
        if vault_env.exists():
            load_dotenv(vault_env)
        elif env_path:
            load_dotenv(env_path)
        else:
            for candidate in [Path.cwd() / ".env", Path.home() / ".env"]:
                if candidate.exists():
                    load_dotenv(candidate)
                    break

        # Re-check vault path after loading .env
        env_vault = os.environ.get("MINDLENS_VAULT_PATH")
        if env_vault:
            vault = Path(env_vault)

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

    @property
    def core_db_path(self) -> Path:
        """Get the core SQLite path."""
        return self.vault_path / ".mindlens" / "core.db"

    @property
    def global_skills_path(self) -> Path:
        """Get the global skills directory."""
        return self.vault_path / ".mindlens" / "skills"

    @property
    def global_instructions_path(self) -> Path:
        """Get the global instructions directory."""
        return self.vault_path / ".mindlens" / "instructions"

    @property
    def agents_path(self) -> Path:
        """Get the agent definitions directory (visible in Obsidian)."""
        return self.vault_path / "agents"

    @property
    def scheduled_tasks_path(self) -> Path:
        """Get the global scheduled tasks file (vault root)."""
        return self.vault_path / "tasks.yaml"

    @property
    def copilot_transcripts_path(self) -> Path | None:
        """Auto-discover VS Code Copilot chat transcripts path."""
        import platform
        system = platform.system()
        if system == "Darwin":
            code_user = Path.home() / "Library" / "Application Support" / "Code" / "User"
        elif system == "Linux":
            code_user = Path.home() / ".config" / "Code" / "User"
        elif system == "Windows":
            code_user = Path.home() / "AppData" / "Roaming" / "Code" / "User"
        else:
            return None

        ws_storage = code_user / "workspaceStorage"
        if not ws_storage.exists():
            return None

        # Auto-discover: find first workspaceStorage ID with copilot-chat transcripts
        for d in sorted(ws_storage.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            transcripts = d / "GitHub.copilot-chat" / "transcripts"
            if transcripts.exists() and any(transcripts.glob("*.jsonl")):
                return transcripts
        return None

    def workspace_tasks_path(self, name: str) -> Path:
        """Get per-workspace tasks.yaml."""
        return self.vault_path / name / "tasks.yaml"
