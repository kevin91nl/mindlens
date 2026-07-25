"""Workspace runtime — manages workspace state and agent swarms."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mindlens.core.event_bus import Event

logger = logging.getLogger(__name__)


@dataclass
class Workspace:
    """A MindLens workspace — an autonomous organizational unit."""

    name: str
    mission: str = ""
    path: Path = field(default_factory=lambda: Path())
    repos: list[dict[str, str]] = field(default_factory=list)
    constitution: str = ""
    autonomy_level: str = "medium"

    @classmethod
    def from_vault(cls, vault_path: Path, name: str) -> Workspace:
        """Load a workspace from the vault."""
        ws_path = vault_path / name
        if not ws_path.exists():
            raise FileNotFoundError(f"Workspace '{name}' not found at {ws_path}")

        # Load constitution
        constitution_path = ws_path / "constitution.md"
        constitution = constitution_path.read_text() if constitution_path.exists() else ""

        # Extract mission from constitution
        mission = ""
        for line in constitution.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-") and not line.startswith("**"):
                mission = line
                break

        # Load repos
        repos_path = ws_path / "repos.yaml"
        repos = []
        if repos_path.exists():
            repos_data = yaml.safe_load(repos_path.read_text()) or {}
            repos = repos_data.get("repos", [])

        # Extract autonomy level
        autonomy = "medium"
        for line in constitution.splitlines():
            if "autonomy level" in line.lower():
                next_lines = constitution[constitution.index(line):].splitlines()[1:3]
                for nl in next_lines:
                    nl = nl.strip().lower()
                    if nl in ("high", "medium", "low"):
                        autonomy = nl
                        break

        return cls(
            name=name,
            mission=mission,
            path=ws_path,
            repos=repos,
            constitution=constitution,
            autonomy_level=autonomy,
        )

    def skill_index(self) -> list[dict[str, Any]]:
        """Load the workspace skill index."""
        index_path = self.path / ".mindlens" / "skills" / "index.yaml"
        if index_path.exists():
            data = yaml.safe_load(index_path.read_text()) or {}
            return data.get("skills", [])
        return []

    def wiki_pages(self) -> list[Path]:
        """List all wiki pages in the workspace."""
        wiki_dir = self.path / "wiki"
        if wiki_dir.exists():
            return sorted(wiki_dir.glob("**/*.md"))
        return []

    def raw_files(self) -> list[Path]:
        """List all raw files in the workspace."""
        raw_dir = self.path / "raw"
        if raw_dir.exists():
            return sorted(raw_dir.iterdir())
        return []
