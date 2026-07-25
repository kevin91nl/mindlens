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

        elif tool_name == "search_code":
            return self._search_code(context)

        elif tool_name == "scan_python_imports":
            return self._scan_python_imports()

        elif tool_name == "check_yaml_consistency":
            return self._check_yaml_consistency()

        elif tool_name == "verify_vault_structure":
            return self._verify_vault_structure()

        elif tool_name == "check_dead_references":
            return self._check_dead_references()

        elif tool_name == "list_events":
            return self._list_events()

        elif tool_name == "query_agent_runs":
            return self._query_agent_runs(context)

        return ""

    def _search_code(self, context: AgentContext) -> str:
        """Search for code patterns in the project."""
        import subprocess
        project = Path.home() / "projects" / "mindlens"
        query = context.task[:50]
        try:
            result = subprocess.run(
                ["grep", "-rn", "--include=*.py", query, str(project / "src")],
                capture_output=True, text=True, timeout=10,
            )
            lines = result.stdout.strip().splitlines()[:10]
            return "\n".join(lines) if lines else f"Geen resultaten voor '{query}'"
        except Exception:
            return "Zoekopdracht mislukt"

    def _scan_python_imports(self) -> str:
        """Check for broken Python imports."""
        project = Path.home() / "projects" / "mindlens"
        src = project / "src"
        if not src.exists():
            return "Geen src/ gevonden."

        issues = []
        for py_file in src.rglob("*.py"):
            try:
                content = py_file.read_text()
                for line_num, line in enumerate(content.splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith("from mindlens.") or stripped.startswith("import mindlens."):
                        # Check if the module exists
                        parts = stripped.replace("from ", "").replace("import ", "").split(".")
                        module_path = src / "/".join(parts[:-1]) / "__init__.py"
                        if not module_path.exists() and not (src / "/".join(parts)).with_suffix(".py").exists():
                            issues.append(f"{py_file.name}:{line_num} — {stripped[:60]}")
            except Exception:
                continue

        if not issues:
            return "✅ Alle Python imports zijn geldig."

        return "⚠️ Mogelijk gebroken imports:\n" + "\n".join(f"- {i}" for i in issues[:10])

    def _check_yaml_consistency(self) -> str:
        """Check if YAML agent definitions match Python agents."""
        vault = self.config.vault_path
        project = Path.home() / "projects" / "mindlens"
        issues = []

        # Check YAML agents reference valid tools
        for yaml_path in discover_yaml_agents(vault):
            try:
                data = yaml.safe_load(yaml_path.read_text()) or {}
                name = data.get("name", "?")
                tools = data.get("tools", [])
                for tool in tools:
                    # Check if tool exists in yaml_agent.py
                    yaml_agent_file = project / "src" / "mindlens" / "agents" / "yaml_agent.py"
                    if yaml_agent_file.exists():
                        content = yaml_agent_file.read_text()
                        if f"tool_name == \"{tool}\"" not in content and tool not in ("read_file", "search_code"):
                            issues.append(f"YAML agent '{name}' references tool '{tool}' not implemented")
            except Exception:
                continue

        if not issues:
            return "✅ YAML definities zijn consistent met Python code."

        return "⚠️ Inconsistente YAML definities:\n" + "\n".join(f"- {i}" for i in issues[:10])

    def _verify_vault_structure(self) -> str:
        """Verify expected vault structure."""
        vault = self.config.vault_path
        issues = []

        # Expected files at root
        expected_root = ["CONTEXT.md", "AGENTS.md", "README.md", "tasks.yaml", "issues.yaml", "repos.yaml"]
        for f in expected_root:
            if not (vault / f).exists():
                issues.append(f"Missing root file: {f}")

        # Expected dirs at root
        expected_dirs = ["agents", "docs", "docs/adr"]
        for d in expected_dirs:
            if not (vault / d).is_dir():
                issues.append(f"Missing root directory: {d}")

        # Check each workspace
        for item in vault.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                ws_issues = []
                if not (item / "constitution.md").exists():
                    ws_issues.append("constitution.md")
                if not (item / "tasks.yaml").exists():
                    ws_issues.append("tasks.yaml")
                if not (item / "issues.yaml").exists():
                    ws_issues.append("issues.yaml")
                if not (item / "repos.yaml").exists():
                    ws_issues.append("repos.yaml")
                if not (item / "agents").is_dir():
                    ws_issues.append("agents/")
                if ws_issues:
                    issues.append(f"Workspace '{item.name}' missing: {', '.join(ws_issues)}")

        if not issues:
            return "✅ Vault structuur is compleet."

        return "⚠️ Ontbrekende bestanden:\n" + "\n".join(f"- {i}" for i in issues)

    def _check_dead_references(self) -> str:
        """Check for references to non-existent files or modules."""
        vault = self.config.vault_path
        issues = []

        # Check repos.yaml references
        repos_path = vault / "repos.yaml"
        if repos_path.exists():
            data = yaml.safe_load(repos_path.read_text()) or {}
            for repo in data.get("repos") or []:
                path = Path(repo.get("path", "")).expanduser()
                if not path.exists():
                    issues.append(f"repos.yaml: '{repo.get('name')}' path niet gevonden: {path}")

        # Check workspace repos.yaml
        for item in vault.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                ws_repos = item / "repos.yaml"
                if ws_repos.exists():
                    data = yaml.safe_load(ws_repos.read_text()) or {}
                    for repo in data.get("repos") or []:
                        path = Path(repo.get("path", "")).expanduser()
                        if not path.exists():
                            issues.append(f"{item.name}/repos.yaml: '{repo.get('name')}' path niet gevonden: {path}")

        # Check ADR references in CONTEXT.md
        context_md = vault / "CONTEXT.md"
        if context_md.exists():
            import re
            content = context_md.read_text()
            links = re.findall(r'\[.*?\]\((.*?)\)', content)
            for link in links:
                if link.startswith("http"):
                    continue
                ref_path = vault / link
                if not ref_path.exists():
                    issues.append(f"CONTEXT.md: dode link '{link}'")

        if not issues:
            return "✅ Geen dode referenties gevonden."

        return "❌ Dode referenties:\n" + "\n".join(f"- {i}" for i in issues)

    def _list_events(self) -> str:
        """List recent events from the event bus."""
        events = self.event_bus.history(limit=20)
        if not events:
            return "Geen recente events."

        output = "Recente events:\n"
        for e in events[-15:]:
            output += f"- [{e.source}] {e.topic}: {str(e.data)[:80]}\n"
        return output

    def _query_agent_runs(self, context: AgentContext) -> str:
        """Query agent runs with analysis."""
        import aiosqlite

        try:
            conn = None
            # Try to connect to core DB
            db_path = self.config.core_db_path()
            if not db_path.exists():
                return "Geen agent_runs database gevonden."

            import asyncio

            async def _query():
                conn = await aiosqlite.connect(str(db_path))

                # Summary stats
                cursor = await conn.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes,
                        SUM(input_tokens + output_tokens) as total_tokens,
                        SUM(cost_usd) as total_cost,
                        AVG(duration_seconds) as avg_duration
                    FROM agent_runs
                    WHERE created_at >= DATE('now', '-7 days')
                """)
                summary = await cursor.fetchone()

                # Per-agent breakdown
                cursor = await conn.execute("""
                    SELECT agent_name,
                           COUNT(*) as runs,
                           SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes,
                           SUM(input_tokens + output_tokens) as tokens,
                           AVG(duration_seconds) as avg_dur
                    FROM agent_runs
                    WHERE created_at >= DATE('now', '-7 days')
                    GROUP BY agent_name
                    ORDER BY runs DESC
                """)
                agents = await cursor.fetchall()

                # Trend (daily)
                cursor = await conn.execute("""
                    SELECT DATE(created_at) as day,
                           COUNT(*) as runs,
                           SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes,
                           SUM(input_tokens + output_tokens) as tokens
                    FROM agent_runs
                    WHERE created_at >= DATE('now', '-7 days')
                    GROUP BY day ORDER BY day
                """)
                trend = await cursor.fetchall()

                await conn.close()
                return summary, agents, trend

            summary, agents, trend = asyncio.get_event_loop().run_until_complete(_query())

            output = "Agent Runs (7 dagen):\n"
            if summary:
                total, success, tokens, cost, duration = summary
                rate = (success / total * 100) if total else 0
                output += f"Totaal: {total} runs, {rate:.0f}% success, {tokens} tokens, ${cost:.4f}\n\n"

                output += "Per agent:\n"
                for agent, runs, successes, tokens, dur in agents:
                    r = (successes / runs * 100) if runs else 0
                    output += f"  {agent}: {runs} runs, {r:.0f}% success, {tokens} tokens, {dur:.1f}s avg\n"

                output += "\nTrend:\n"
                for day, runs, successes, tokens in trend:
                    output += f"  {day}: {runs} runs, {tokens} tokens\n"

            return output

        except Exception as e:
            return f"Fout bij ophalen agent runs: {e}"

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
