"""Workspace Manager — creates and manages workspaces and their agent swarms."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from mindlens.agents.base import Agent, AgentContext, AgentResult
from mindlens.core.event_bus import Event

logger = logging.getLogger(__name__)

WORKSPACE_TEMPLATE = """# {name} Workspace — Constitution

## Mission

{mission}

## Priorities

1. Accuracy
2. Speed
3. Completeness

## Forbidden

- Auto-commit code changes without approval
- Modify raw input files
- Skip uncertainty

## Autonomy Level

Medium

## Linked Repos

See `repos.yaml`.
"""


class WorkspaceManager(Agent):
    name = "workspace_manager"
    description = "Creates and manages workspaces and their agent swarms"
    capabilities = ["create_workspace", "list_workspaces", "add_agent", "remove_agent"]

    async def run(self, context: AgentContext) -> AgentResult:
        """Execute workspace management task."""
        task = context.task.lower()

        if "create" in task and "workspace" in task:
            return await self._create_workspace(context)
        elif "list" in task and "workspace" in task:
            return await self._list_workspaces()
        else:
            return AgentResult(
                success=False,
                output=f"Unknown workspace management task: {context.task}",
            )

    async def _create_workspace(self, context: AgentContext) -> AgentResult:
        """Create a new workspace in the vault."""
        # Extract workspace name from task
        # e.g., "Create workspace Marketing" -> "Marketing"
        words = context.task.split()
        name = None
        for i, word in enumerate(words):
            if word.lower() == "workspace" and i + 1 < len(words):
                name = words[i + 1].capitalize()
                break

        if not name:
            return AgentResult(
                success=False,
                output="Could not determine workspace name. Say: 'Create workspace <Name>'",
            )

        ws_path = self.config.workspace_path(name)
        if ws_path.exists():
            return AgentResult(
                success=False,
                output=f"Workspace '{name}' already exists at {ws_path}",
            )

        # Create directory structure
        dirs = [
            ws_path / "raw",
            ws_path / "wiki",
            ws_path / ".mindlens" / "skills",
            ws_path / ".mindlens" / "instructions",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

        # Create constitution
        constitution_path = ws_path / "constitution.md"
        constitution_path.write_text(
            WORKSPACE_TEMPLATE.format(name=name, mission="TBD — describe the mission for this workspace.")
        )

        # Create repos.yaml
        repos_path = ws_path / "repos.yaml"
        repos_path.write_text("repos: []\n")

        # Create skill index
        skill_index = ws_path / ".mindlens" / "skills" / "index.yaml"
        skill_index.write_text(f"# {name} Workspace Skill Index\nskills: []\n")

        # Publish event
        await self.event_bus.publish(Event(
            topic="workspace.created",
            source="workspace_manager",
            data={"workspace": name, "path": str(ws_path)},
        ))

        return AgentResult(
            success=True,
            output=(
                f"✅ Workspace '{name}' created.\n"
                f"  Path: {ws_path}\n"
                f"  Files: constitution.md, repos.yaml\n"
                f"  Directories: raw/, wiki/, .mindlens/\n\n"
                f"Set the mission by editing {constitution_path}"
            ),
        )

    async def _list_workspaces(self) -> AgentResult:
        """List all workspaces in the vault."""
        vault = self.config.vault_path
        workspaces = []

        for item in sorted(vault.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                constitution = item / "constitution.md"
                mission = ""
                if constitution.exists():
                    # Extract first non-empty, non-header line
                    for line in constitution.read_text().splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and not line.startswith("-"):
                            mission = line
                            break

                workspaces.append({
                    "name": item.name,
                    "mission": mission or "(no mission set)",
                    "has_raw": (item / "raw").exists(),
                    "has_wiki": (item / "wiki").exists(),
                })

        if not workspaces:
            return AgentResult(success=True, output="No workspaces found.")

        output = "📂 Workspaces:\n\n"
        for ws in workspaces:
            output += f"• **{ws['name']}** — {ws['mission']}\n"

        return AgentResult(success=True, output=output)
