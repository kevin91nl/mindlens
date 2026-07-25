"""YAML Agent — generic agent that runs from YAML definitions in the vault.

This is the core of the agentic-driven architecture. Agents are defined in YAML
files in the vault (e.g., Cortex/agents/session_observer.yaml). The Python runtime
reads these definitions and executes them — no Python code needed per agent.

Adding a new agent = adding a YAML file to the vault.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import yaml

from mindlens.agents.base import Agent, AgentContext, AgentResult
from mindlens.core.vscode_sessions import VSCodeSessionReader

logger = logging.getLogger(__name__)


class YamlAgent(Agent):
    """Agent that runs from a YAML definition file."""

    def __init__(self, yaml_path: Path, **kwargs: Any) -> None:
        self.yaml_path = yaml_path
        self._config = yaml.safe_load(yaml_path.read_text()) or {}

        # Override base class attributes from YAML
        self.name = self._config.get("name", yaml_path.stem)
        self.description = self._config.get("description", "")
        self.capabilities = self._config.get("capabilities", [])
        self.scope = self._config.get("scope", "global")

        self._system_prompt = self._config.get("system_prompt", "")
        self._tools = self._config.get("tools", [])
        self._notify = self._config.get("notify", "summary")
        self._schedule = self._config.get("schedule")

        super().__init__(**kwargs)

    @classmethod
    def from_yaml(cls, yaml_path: Path, **kwargs: Any) -> YamlAgent:
        """Create a YamlAgent from a YAML file path."""
        return cls(yaml_path=yaml_path, **kwargs)

    async def run(self, context: AgentContext) -> AgentResult:
        """Execute the agent based on its YAML definition."""
        # Gather tool data based on configured tools
        tool_data = await self._gather_tool_data(context)

        # Build the prompt
        user_message = f"Taak: {context.task}\n"
        if context.workspace:
            user_message += f"Werkruimte: {context.workspace}\n"
        if tool_data:
            user_message += f"\nBeschikbare data:\n{tool_data}"

        # Call LLM with the YAML-defined system prompt
        content, in_tok, out_tok = await self._llm_complete(
            self._system_prompt,
            user_message,
            temperature=0.3,
        )

        return AgentResult(
            success=True,
            output=content,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )

    async def _gather_tool_data(self, context: AgentContext) -> str:
        """Gather data from configured tools."""
        data_parts = []

        for tool in self._tools:
            try:
                result = await self._execute_tool(tool, context)
                if result:
                    data_parts.append(f"### {tool}\n{result}")
            except Exception as e:
                logger.debug("Tool %s failed: %s", tool, e)

        return "\n\n".join(data_parts) if data_parts else ""

    async def _execute_tool(self, tool_name: str, context: AgentContext) -> str:
        """Execute a tool and return its output."""
        vault = self.config.vault_path

        if tool_name == "list_sessions":
            reader = VSCodeSessionReader()
            sessions = reader.list_sessions(limit=10)
            if not sessions:
                return "Geen sessies gevonden."
            output = ""
            for s in sessions:
                output += f"- {s.session_id[:8]} | {s.workspace_name} | {s.started[:16]} | {len(s.messages)} msgs | {s.first_message[:60]}\n"
            return output

        elif tool_name == "search_sessions":
            reader = VSCodeSessionReader()
            sessions = reader.search_sessions(context.task, limit=5)
            if not sessions:
                return "Geen sessies gevonden."
            output = ""
            for s in sessions:
                output += f"- {s.session_id[:8]} | {s.workspace_name} | {s.first_message[:80]}\n"
            return output

        elif tool_name == "list_agent_runs":
            import aiosqlite
            try:
                conn = await aiosqlite.connect(str(self.config.core_db_path()))
                cursor = await conn.execute("""
                    SELECT agent_name, workspace, task_description, success,
                           input_tokens + output_tokens as tokens, cost_usd, duration_seconds
                    FROM agent_runs
                    WHERE created_at >= DATE('now', '-2 days')
                    ORDER BY created_at DESC
                    LIMIT 20
                """)
                rows = await cursor.fetchall()
                await conn.close()
                if not rows:
                    return "Geen agent runs gevonden."
                output = ""
                for agent, ws, task, success, tokens, cost, duration in rows:
                    icon = "✅" if success else "❌"
                    output += f"{icon} {agent} [{ws}]: {(task or '')[:60]} | {tokens} tokens | ${cost:.4f} | {duration:.1f}s\n"
                return output
            except Exception as e:
                return f"Fout bij ophalen runs: {e}"

        elif tool_name == "list_workspaces":
            workspaces = []
            for item in vault.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    constitution = item / "constitution.md"
                    if constitution.exists():
                        workspaces.append(item.name)
            return ", ".join(workspaces) if workspaces else "Geen workspaces gevonden."

        elif tool_name == "list_issues":
            ws = context.workspace or "global"
            issues_path = vault / ws / "issues.yaml" if ws != "global" else vault / "issues.yaml"
            if not issues_path.exists():
                return f"Geen issues in {ws}."
            data = yaml.safe_load(issues_path.read_text()) or {}
            issues = data.get("issues") or []
            if not issues:
                return f"Geen issues in {ws}."
            output = ""
            for i in issues:
                output += f"- {i.get('id', '?')} | {i.get('status', '?')} | {i.get('title', '?')}\n"
            return output

        elif tool_name == "list_tasks":
            ws = context.workspace or "global"
            tasks_path = vault / ws / "tasks.yaml" if ws != "global" else vault / "tasks.yaml"
            if not tasks_path.exists():
                return f"Geen tasks in {ws}."
            data = yaml.safe_load(tasks_path.read_text()) or {}
            tasks = data.get("tasks") or []
            if not tasks:
                return f"Geen tasks in {ws}."
            output = ""
            for t in tasks:
                output += f"- {t.get('name', '?')} | {t.get('schedule', '?')} | {t.get('agent', '?')}\n"
            return output

        elif tool_name == "list_skills":
            all_skills = []
            global_index = vault / ".mindlens" / "skills" / "index.yaml"
            if global_index.exists():
                idx = yaml.safe_load(global_index.read_text()) or {}
                for s in idx.get("skills") or []:
                    all_skills.append(f"[global] {s.get('name', '?')}: {s.get('description', '?')[:60]}")
            for item in vault.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    ws_index = item / ".mindlens" / "skills" / "index.yaml"
                    if ws_index.exists():
                        idx = yaml.safe_load(ws_index.read_text()) or {}
                        for s in idx.get("skills") or []:
                            all_skills.append(f"[{item.name}] {s.get('name', '?')}: {s.get('description', '?')[:60]}")
            return "\n".join(all_skills) if all_skills else "Geen skills gevonden."

        elif tool_name == "create_issue":
            # Handled by LLM decision — return placeholder
            return ""

        elif tool_name == "create_skill":
            return ""

        elif tool_name == "read_wiki":
            ws = context.workspace
            if not ws:
                return "Geen werkruimte opgegeven."
            wiki_dir = vault / ws / "wiki"
            if not wiki_dir.exists():
                return f"Geen wiki in {ws}."
            pages = [p.stem for p in wiki_dir.glob("*.md")]
            return f"Wiki pagina's in {ws}: {', '.join(pages)}" if pages else f"Geen wiki pagina's in {ws}."

        return ""

    def create_github_issue(self, title: str, body: str, labels: list[str]) -> str | None:
        """Create a GitHub issue using gh CLI."""
        try:
            # Find the repo path from repos.yaml
            repos_path = self.config.vault_path / "repos.yaml"
            cwd = str(Path.home() / "projects" / "mindlens")  # default
            if repos_path.exists():
                repos_data = yaml.safe_load(repos_path.read_text()) or {}
                for repo in repos_data.get("repos") or []:
                    if repo.get("type") == "core":
                        cwd = str(Path(repo.get("path", "")).expanduser())
                        break

            result = subprocess.run(
                ["gh", "issue", "create",
                 "--title", title,
                 "--body", body,
                 "--label", ",".join(labels)],
                capture_output=True, text=True, timeout=30, cwd=cwd,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception:
            return None


def discover_yaml_agents(vault_path: Path) -> list[Path]:
    """Discover all YAML agent definitions in the vault."""
    agents = []

    # Global agents
    global_dir = vault_path / "agents"
    if global_dir.exists():
        agents.extend(sorted(global_dir.glob("*.yaml")))

    # Workspace agents
    for item in vault_path.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            ws_agents = item / "agents"
            if ws_agents.exists():
                agents.extend(sorted(ws_agents.glob("*.yaml")))

    return agents
