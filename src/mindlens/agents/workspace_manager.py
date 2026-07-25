"""Workspace Manager — creates and manages workspaces and their agent swarms."""

from __future__ import annotations

import json
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

SYSTEM_PROMPT = """You are the Workspace Manager of MindLens.

Your task is to handle workspace management requests.

You can:
- Create workspaces
- List workspaces
- Add agents to workspaces

ALWAYS respond with a JSON object:
{
    "action": "create" | "list" | "add_agent" | "unknown",
    "workspace_name": "name of the workspace (only for create/add_agent)",
    "mission": "mission for the workspace (only for create, optional)",
    "agent_name": "name of the agent (only for add_agent)"
}

Examples:
- "Create workspace Persoonlijk" → {"action": "create", "workspace_name": "Persoonlijk", "mission": ""}
- "Create workspace Marketing for campaigns" → {"action": "create", "workspace_name": "Marketing", "mission": "Marketing campaigns"}
- "What workspaces exist?" → {"action": "list"}
- "Add marktplaats agent to Persoonlijk" → {"action": "add_agent", "workspace_name": "Persoonlijk", "agent_name": "marktplaats"}

Always respond in the same language as the user's message.
If you don't understand the action, use "unknown".
"""


class WorkspaceManager(Agent):
    name = "workspace_manager"
    description = "Creates and manages workspaces and their agent swarms"
    capabilities = ["create_workspace", "list_workspaces", "add_agent", "remove_agent"]

    def _list_workspace_names(self) -> list[str]:
        """List existing workspace directory names."""
        vault = self.config.vault_path
        return sorted(
            item.name
            for item in vault.iterdir()
            if item.is_dir() and not item.name.startswith((".", "_"))
        )

    async def run(self, context: AgentContext) -> AgentResult:
        """Execute workspace management task using LLM for intent parsing."""
        # Quick keyword shortcuts for common operations
        task_lower = context.task.lower()
        if task_lower in ("list", "list workspaces"):
            return await self._list_workspaces()

        # Use LLM to parse intent
        ws_names = self._list_workspace_names()
        user_msg = f"Request: {context.task}\n\nExisting workspaces: {', '.join(ws_names)}"

        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT, user_msg, temperature=0.1
        )

        # Parse JSON response
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_str = content
            if "```" in content:
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("{"):
                        json_str = line
                        break
            intent = json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            return AgentResult(
                success=False,
                output=f"Could not understand request: {content}",
                input_tokens=in_tok,
                output_tokens=out_tok,
            )

        action = intent.get("action", "unknown")

        if action == "create":
            return await self._create_workspace(
                name=intent.get("workspace_name", ""),
                mission=intent.get("mission", ""),
                input_tokens=in_tok,
                output_tokens=out_tok,
            )
        elif action == "list":
            return await self._list_workspaces()
        elif action == "add_agent":
            return await self._add_agent_to_workspace(
                workspace=intent.get("workspace_name", ""),
                agent_name=intent.get("agent_name", ""),
                input_tokens=in_tok,
                output_tokens=out_tok,
            )
        else:
            return AgentResult(
                success=False,
                output=f"Could not process request: {context.task}",
                input_tokens=in_tok,
                output_tokens=out_tok,
            )

    async def _create_workspace(
        self,
        name: str,
        mission: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> AgentResult:
        """Create a new workspace in the vault."""
        if not name:
            return AgentResult(
                success=False,
                output="No workspace name provided.",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        ws_path = self.config.workspace_path(name)
        if ws_path.exists():
            return AgentResult(
                success=False,
                output=f"Workspace '{name}' already exists at {ws_path}",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        # Create directory structure
        dirs = [
            ws_path / "raw",
            ws_path / "wiki",
            ws_path / "agents",
            ws_path / ".mindlens" / "skills",
            ws_path / ".mindlens" / "instructions",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

        # Create constitution
        constitution_path = ws_path / "constitution.md"
        constitution_path.write_text(
            WORKSPACE_TEMPLATE.format(
                name=name,
                mission=mission or "TBD — describe the mission for this workspace.",
            )
        )

        # Create repos.yaml
        repos_path = ws_path / "repos.yaml"
        repos_path.write_text("repos: []\n")

        # Create tasks.yaml
        tasks_path = ws_path / "tasks.yaml"
        tasks_path.write_text("tasks: []\n")

        # Create issues.yaml
        issues_path = ws_path / "issues.yaml"
        issues_path.write_text("issues: []\n")

        # Create agent index
        agent_index = ws_path / "agents" / "INDEX.md"
        agent_index.write_text(f"# {name} Agents\n\nNo agents defined yet.\n")

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
                f"  Directories: raw/, wiki/, agents/, .mindlens/\n"
                f"  Files: constitution.md, repos.yaml, tasks.yaml, issues.yaml\n\n"
                f"Edit the mission in {constitution_path}"
            ),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def _list_workspaces(self) -> AgentResult:
        """List all workspaces in the vault."""
        vault = self.config.vault_path
        workspaces = []

        for item in sorted(vault.iterdir()):
            if item.is_dir() and not item.name.startswith((".", "_")):
                constitution = item / "constitution.md"
                mission = ""
                if constitution.exists():
                    for line in constitution.read_text().splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and not line.startswith("-"):
                            mission = line
                            break

                workspaces.append({
                    "name": item.name,
                    "mission": mission or "(no mission set)",
                })

        if not workspaces:
            return AgentResult(success=True, output="No workspaces found.")

        output = "📂 Workspaces:\n\n"
        for ws in workspaces:
            output += f"• **{ws['name']}** — {ws['mission']}\n"

        return AgentResult(success=True, output=output)

    async def _add_agent_to_workspace(
        self,
        workspace: str,
        agent_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> AgentResult:
        """Add a placeholder agent YAML to a workspace."""
        if not workspace or not agent_name:
            return AgentResult(
                success=False,
                output="No workspace or agent name provided.",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        ws_path = self.config.workspace_path(workspace)
        if not ws_path.exists():
            return AgentResult(
                success=False,
                output=f"Workspace '{workspace}' does not exist.",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        agents_dir = ws_path / "agents"
        agents_dir.mkdir(exist_ok=True)

        agent_file = agents_dir / f"{agent_name.lower().replace(' ', '_')}.yaml"
        if agent_file.exists():
            return AgentResult(
                success=False,
                output=f"Agent '{agent_name}' already exists in {workspace}.",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        agent_file.write_text(
            f"# {agent_name.title()} — Agent Definition\n"
            f"name: {agent_name.lower().replace(' ', '_')}\n"
            f"description: TBD — describe this agent\n"
            f"type: workspace\n"
            f"capabilities: []\n\n"
            f"system_prompt: |\n"
            f"  You are the {agent_name.title()} agent in the {workspace} workspace.\n"
            f"  TBD — define your behavior here.\n"
        )

        await self.event_bus.publish(Event(
            topic="agent.created",
            source="workspace_manager",
            data={"workspace": workspace, "agent": agent_name, "path": str(agent_file)},
        ))

        return AgentResult(
            success=True,
            output=(
                f"✅ Agent '{agent_name}' added to {workspace}.\n"
                f"  File: {agent_file}\n\n"
                f"Edit the system_prompt in the YAML file."
            ),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
