"""Agent base class and registry."""

from __future__ import annotations

import abc
import json
import logging
import uuid
import yaml
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    """Context passed to an agent for a single task execution."""

    task: str
    workspace: str | None = None
    skills: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Result from an agent execution."""

    success: bool
    output: str
    input_tokens: int = 0
    output_tokens: int = 0
    skills_loaded: list[str] = field(default_factory=list)
    skills_useful: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class Agent(abc.ABC):
    """Base class for all MindLens agents.

    Scope rules (ADR-007):
    - Global agents (defined in /agents/) can modify everything.
    - Workspace agents (defined in <Workspace>/agents/) can only modify their own workspace.
    - Telegram = global scope (Chief of Staff can do everything).
    """

    name: str = "base_agent"
    description: str = "Base agent"
    capabilities: list[str] = []
    scope: str = "global"  # "global" or workspace name

    def __init__(
        self,
        llm: Any,  # LLMClient
        event_bus: Any,  # EventBus
        config: Any,  # Config
    ) -> None:
        self.llm = llm
        self.event_bus = event_bus
        self.config = config

    def _check_scope(self, workspace: str) -> bool:
        """Check if this agent can operate on the given workspace."""
        if self.scope == "global":
            return True
        return self.scope == workspace

    def _scope_error(self, workspace: str) -> str:
        """Return an error message for scope violations."""
        return f"Scope violation: agent '{self.name}' (scope={self.scope}) cannot modify workspace '{workspace}'"

    # --- Task management (scope-aware) ---

    def _tasks_path(self, workspace: str) -> Path:
        """Get tasks.yaml path for a workspace."""
        if workspace == "global":
            return self.config.vault_path / "tasks.yaml"
        return self.config.vault_path / workspace / "tasks.yaml"

    def add_task(self, workspace: str, name: str, schedule: str, agent: str, message: str, enabled: bool = True) -> str:
        """Add a scheduled task. Returns status message."""
        if not self._check_scope(workspace):
            return self._scope_error(workspace)

        path = self._tasks_path(workspace)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {}
        if path.exists():
            data = yaml.safe_load(path.read_text()) or {}

        tasks = data.get("tasks") or []
        # Check for duplicate
        if any(t.get("name") == name for t in tasks):
            return f"Task '{name}' already exists in {workspace}"

        tasks.append({
            "name": name,
            "schedule": schedule,
            "agent": agent,
            "workspace": workspace if workspace != "global" else "HQ",
            "message": message,
            "enabled": enabled,
        })
        data["tasks"] = tasks
        path.write_text(yaml.dump(data, default_flow_style=False))
        return f"✅ Task '{name}' added to {workspace}/tasks.yaml"

    def remove_task(self, workspace: str, name: str) -> str:
        """Remove a scheduled task by name."""
        if not self._check_scope(workspace):
            return self._scope_error(workspace)

        path = self._tasks_path(workspace)
        if not path.exists():
            return f"No tasks.yaml in {workspace}"

        data = yaml.safe_load(path.read_text()) or {}
        tasks = data.get("tasks") or []
        before = len(tasks)
        tasks = [t for t in tasks if t.get("name") != name]

        if len(tasks) == before:
            return f"Task '{name}' not found in {workspace}"

        data["tasks"] = tasks
        path.write_text(yaml.dump(data, default_flow_style=False))
        return f"✅ Task '{name}' removed from {workspace}/tasks.yaml"

    def list_tasks(self, workspace: str) -> str:
        """List scheduled tasks for a workspace."""
        if not self._check_scope(workspace):
            return self._scope_error(workspace)

        path = self._tasks_path(workspace)
        if not path.exists():
            return f"No tasks.yaml in {workspace}"

        data = yaml.safe_load(path.read_text()) or {}
        tasks = data.get("tasks") or []
        if not tasks:
            return f"No tasks in {workspace}"

        output = f"📋 Tasks in {workspace}:\n"
        for t in tasks:
            status = "✅" if t.get("enabled", True) else "⏸️"
            output += f"  {status} {t['name']} | {t['schedule']} | {t.get('agent', '?')}\n"
        return output.strip()

    # --- Issue management (scope-aware, kanban) ---

    def _issues_path(self, workspace: str) -> Path:
        """Get issues.yaml path for a workspace."""
        if workspace == "global":
            return self.config.vault_path / "issues.yaml"
        return self.config.vault_path / workspace / "issues.yaml"

    def _load_issues(self, workspace: str) -> list[dict]:
        """Load issues from YAML."""
        path = self._issues_path(workspace)
        if not path.exists():
            return []
        data = yaml.safe_load(path.read_text()) or {}
        return data.get("issues") or []

    def _save_issues(self, workspace: str, issues: list[dict]) -> None:
        """Save issues to YAML."""
        path = self._issues_path(workspace)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump({"issues": issues}, default_flow_style=False, allow_unicode=True))

    def add_issue(self, workspace: str, title: str, description: str = "",
                  priority: str = "medium", assignee: str = "") -> str:
        """Add a new issue."""
        if not self._check_scope(workspace):
            return self._scope_error(workspace)

        issues = self._load_issues(workspace)
        prefix = workspace.upper()[:3] if workspace != "global" else "MIND"
        next_num = len(issues) + 1
        issue_id = f"{prefix}-{next_num:03d}"

        from datetime import date
        issue = {
            "id": issue_id,
            "title": title,
            "status": "backlog",
            "priority": priority,
            "assignee": assignee,
            "description": description,
            "created": str(date.today()),
            "updated": str(date.today()),
        }
        issues.append(issue)
        self._save_issues(workspace, issues)
        return f"✅ Issue {issue_id} created: {title}"

    def update_issue(self, workspace: str, issue_id: str, **fields) -> str:
        """Update an issue's fields (status, priority, assignee, title, description)."""
        if not self._check_scope(workspace):
            return self._scope_error(workspace)

        issues = self._load_issues(workspace)
        for issue in issues:
            if issue.get("id") == issue_id:
                from datetime import date
                for key, value in fields.items():
                    if key in ("status", "priority", "assignee", "title", "description"):
                        issue[key] = value
                issue["updated"] = str(date.today())
                self._save_issues(workspace, issues)
                return f"✅ Issue {issue_id} updated: {fields}"
        return f"Issue {issue_id} not found in {workspace}"

    def remove_issue(self, workspace: str, issue_id: str) -> str:
        """Remove an issue."""
        if not self._check_scope(workspace):
            return self._scope_error(workspace)

        issues = self._load_issues(workspace)
        before = len(issues)
        issues = [i for i in issues if i.get("id") != issue_id]
        if len(issues) == before:
            return f"Issue {issue_id} not found in {workspace}"
        self._save_issues(workspace, issues)
        return f"✅ Issue {issue_id} removed"

    def list_issues(self, workspace: str, status: str | None = None) -> str:
        """List issues, optionally filtered by status."""
        if not self._check_scope(workspace):
            return self._scope_error(workspace)

        issues = self._load_issues(workspace)
        if status:
            issues = [i for i in issues if i.get("status") == status]
        if not issues:
            return f"No issues{f' ({status})' if status else ''} in {workspace}"

        icons = {"backlog": "📥", "todo": "📝", "in_progress": "🔄", "review": "👀", "done": "✅", "blocked": "🚫"}
        output = f"📋 Issues in {workspace}:\n"
        for i in issues:
            icon = icons.get(i.get("status", ""), "❓")
            prio = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(i.get("priority"), "⚪")
            output += f"  {icon} {i['id']} | {prio} {i.get('title', '?')} → {i.get('assignee', '?')}\n"
        return output.strip()

    def get_issue(self, workspace: str, issue_id: str) -> str:
        """Get full details of an issue."""
        if not self._check_scope(workspace):
            return self._scope_error(workspace)

        issues = self._load_issues(workspace)
        for i in issues:
            if i.get("id") == issue_id:
                output = f"📋 {i['id']}: {i.get('title', '?')}\n"
                output += f"  Status: {i.get('status', '?')}\n"
                output += f"  Priority: {i.get('priority', '?')}\n"
                output += f"  Assignee: {i.get('assignee', '?')}\n"
                output += f"  Description: {i.get('description', '?')}\n"
                output += f"  Created: {i.get('created', '?')} | Updated: {i.get('updated', '?')}\n"
                if i.get("subtasks"):
                    output += f"  Subtasks:\n"
                    for st in i["subtasks"]:
                        output += f"    - {st}\n"
                return output
        return f"Issue {issue_id} not found in {workspace}"

    # --- Wiki management (scope-aware) ---

    def read_wiki(self, workspace: str, page_name: str) -> str:
        """Read a wiki page."""
        if not self._check_scope(workspace):
            return self._scope_error(workspace)

        wiki_dir = self.config.workspace_path(workspace) / "wiki"
        page_path = wiki_dir / f"{page_name}.md"
        if not page_path.exists():
            return f"Wiki page '{page_name}' not found in {workspace}"

        return page_path.read_text(encoding="utf-8", errors="replace")

    def write_wiki(self, workspace: str, page_name: str, content: str) -> str:
        """Write a wiki page. Workspace agents can only write to their own workspace."""
        if not self._check_scope(workspace):
            return self._scope_error(workspace)

        wiki_dir = self.config.workspace_path(workspace) / "wiki"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        page_path = wiki_dir / f"{page_name}.md"
        page_path.write_text(content, encoding="utf-8")
        return f"✅ Wiki page '{page_name}' written to {workspace}/wiki/"

    def list_wiki(self, workspace: str) -> str:
        """List wiki pages in a workspace."""
        if not self._check_scope(workspace):
            return self._scope_error(workspace)

        wiki_dir = self.config.workspace_path(workspace) / "wiki"
        if not wiki_dir.exists():
            return f"No wiki in {workspace}"

        pages = sorted(wiki_dir.glob("*.md"))
        if not pages:
            return f"No wiki pages in {workspace}"

        output = f"📚 Wiki pages in {workspace}:\n"
        for p in pages:
            output += f"  • {p.stem}\n"
        return output.strip()

    # --- Agent management (scope-aware) ---

    def list_agents_in_scope(self, workspace: str | None = None) -> str:
        """List agents in scope."""
        agents = []

        # Global agents
        global_dir = self.config.agents_path()
        if global_dir.exists():
            for f in sorted(global_dir.glob("*.yaml")):
                data = yaml.safe_load(f.read_text()) or {}
                agents.append(f"  🌐 {data.get('name', f.stem)} — {data.get('description', '?')}")

        # Workspace agents
        if workspace:
            ws_dir = self.config.workspace_path(workspace) / "agents"
            if ws_dir.exists():
                for f in sorted(ws_dir.glob("*.yaml")):
                    data = yaml.safe_load(f.read_text()) or {}
                    agents.append(f"  📁 {data.get('name', f.stem)} — {data.get('description', '?')}")

        if not agents:
            return "No agents found"

        return "🤖 Agents:\n" + "\n".join(agents)

    @abc.abstractmethod
    async def run(self, context: AgentContext) -> AgentResult:
        """Execute the agent's task."""
        ...

    async def _llm_complete(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
    ) -> tuple[str, int, int]:
        """Helper: send a system+user message to the LLM. Returns (content, in_tokens, out_tokens)."""
        response = await self.llm.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
        )
        return response.content, response.input_tokens, response.output_tokens

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Strip markdown code fences from LLM responses."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            lines = lines[1:]  # Remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]  # Remove closing fence
            cleaned = "\n".join(lines).strip()
        return cleaned


class AgentRegistry:
    """Registry of available agents."""

    def __init__(self) -> None:
        self._agents: dict[str, type[Agent]] = {}

    def register(self, agent_cls: type[Agent]) -> None:
        """Register an agent class."""
        self._agents[agent_cls.name] = agent_cls
        logger.debug("Registered agent: %s", agent_cls.name)

    def get(self, name: str) -> type[Agent] | None:
        """Get an agent class by name."""
        return self._agents.get(name)

    def list_agents(self) -> list[dict[str, str]]:
        """List all registered agents."""
        return [
            {"name": cls.name, "description": cls.description}
            for cls in self._agents.values()
        ]

    def create(
        self,
        name: str,
        llm: Any,
        event_bus: Any,
        config: Any,
        scope: str = "global",
    ) -> Agent | None:
        """Create an agent instance by name with scope."""
        cls = self._agents.get(name)
        if cls:
            # Check if this is a YAML agent (has _yaml_path)
            yaml_path = getattr(cls, "_yaml_path", None)
            if yaml_path:
                from mindlens.agents.yaml_agent import YamlAgent
                agent = YamlAgent.from_yaml(yaml_path, llm=llm, event_bus=event_bus, config=config)
                agent.scope = scope
                return agent
            agent = cls(llm=llm, event_bus=event_bus, config=config)
            agent.scope = scope
            return agent
        return None
