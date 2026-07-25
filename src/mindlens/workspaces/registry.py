"""Workspace registry — manages all workspaces."""

from __future__ import annotations

import logging
from pathlib import Path

from mindlens.workspaces.workspace import Workspace

logger = logging.getLogger(__name__)


class WorkspaceRegistry:
    """Registry of all workspaces loaded from the vault."""

    def __init__(self, vault_path: Path) -> None:
        self.vault_path = vault_path
        self._workspaces: dict[str, Workspace] = {}

    def discover(self) -> list[str]:
        """Discover all workspaces in the vault."""
        found = []
        for item in self.vault_path.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                constitution = item / "constitution.md"
                if constitution.exists():
                    found.append(item.name)
        return found

    def load(self, name: str) -> Workspace:
        """Load a workspace by name."""
        if name not in self._workspaces:
            self._workspaces[name] = Workspace.from_vault(self.vault_path, name)
        return self._workspaces[name]

    def load_all(self) -> dict[str, Workspace]:
        """Load all discovered workspaces."""
        for name in self.discover():
            if name not in self._workspaces:
                try:
                    self._workspaces[name] = Workspace.from_vault(self.vault_path, name)
                except Exception:
                    logger.exception("Failed to load workspace %s", name)
        return dict(self._workspaces)

    def list_names(self) -> list[str]:
        """List all loaded workspace names."""
        return list(self._workspaces.keys())
