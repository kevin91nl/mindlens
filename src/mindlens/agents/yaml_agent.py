"""YAML Agent — generic agent that runs from YAML definitions in the vault.

This is the core of the agentic-driven architecture. Agents are defined in YAML
files in the vault (e.g., Cortex/agents/session_observer.yaml). The Python runtime
reads these definitions and executes them — no Python code needed per agent.

Adding a new agent = adding a YAML file to the vault.
"""

from __future__ import annotations

import json
import logging
import os
import re
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
        self._tools = self._config.get("tools") or []
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

        # Call LLM — use agentic loop if mode=agentic, else single call
        mode = self._config.get("mode", "single")
        if mode == "agentic":
            content, in_tok, out_tok = await self._agentic_loop(
                self._system_prompt, user_message, context
            )
        else:
            content, in_tok, out_tok = await self._llm_complete(
                self._system_prompt, user_message, temperature=0.3,
            )

        # Post-process: create GitHub issues if LLM suggested them
        created_issues = await self._create_issues_from_response(content)

        # Post-process: execute triage actions (close/comment/label) from LLM output
        triage_actions = await self._execute_triage_actions(content)

        output = content
        if created_issues:
            output += "\n\n---\n📋 GitHub issues aangemaakt:\n"
            for issue_url in created_issues:
                output += f"  ✅ {issue_url}\n"
        if triage_actions:
            output += "\n\n---\n🔧 Triage acties uitgevoerd:\n"
            for action in triage_actions:
                output += f"  {action}\n"

        return AgentResult(
            success=True,
            output=output,
            input_tokens=in_tok,
            output_tokens=out_tok,
            metadata={"created_issues": created_issues, "triage_actions": triage_actions},
        )

    async def _create_issues_from_response(self, content: str) -> list[str]:
        """Parse LLM response for issue suggestions and create them."""
        import re

        created = []

        # Strategy 1: Look for JSON blocks (object or array)
        json_blocks = re.findall(r'```json\s*(.+?)\s*```', content, re.DOTALL)
        for block in json_blocks:
            try:
                data = json.loads(block)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            url = self._try_create_issue(item)
                            if url:
                                created.append(url)
                elif isinstance(data, dict):
                    url = self._try_create_issue(data)
                    if url:
                        created.append(url)
            except json.JSONDecodeError:
                continue

        # Strategy 2: Look for gh issue create commands
        gh_blocks = re.findall(r'```bash\s*(gh issue create[^`]*)\s*```', content, re.DOTALL)
        for block in gh_blocks:
            try:
                title_match = re.search(r'--title\s+"([^"]+)"', block)
                body_match = re.search(r'--body\s+"([^"]+)"', block)
                label_match = re.search(r'--label\s+"([^"]+)"', block)

                if title_match:
                    title = title_match.group(1)
                    body = body_match.group(1) if body_match else ""
                    labels = label_match.group(1).split(",") if label_match else ["bug"]

                    url = self.create_github_issue(title, body, [l.strip() for l in labels])
                    if url:
                        created.append(url)
            except Exception:
                continue

        # Strategy 3: Look for inline issue suggestions (### Bug N: title)
        bug_sections = re.findall(r'###\s*(?:Bug|Issue)\s*\d*:\s*(.+?)(?:\n|$)', content)
        for title in bug_sections:
            title = title.strip()
            if not title:
                continue
            if any(title[:30] in c for c in created):
                continue
            url = self.create_github_issue(
                f"[Auto] {title}",
                f"## Auto-detected by {self.name}\n\n{content[:500]}",
                ["bug"],
            )
            if url:
                created.append(url)

        return created

    def _try_create_issue(self, data: dict) -> str | None:
        """Try to create a GitHub issue from parsed JSON data."""
        title = data.get("title")
        if not title:
            return None

        # Reject template placeholders
        if "{" in title or "}" in title or title.lower() in ("title", "description", "todo"):
            return None

        description = data.get("description", "")
        if "{" in description[:20] or description.lower() in ("description", "todo"):
            return None

        if any(k in data for k in ("severity", "description", "suggested_fix")):
            labels = data.get("labels", ["bug"])
            body = f"## Auto-detected by {self.name}\n\n{data.get('description', '')}\n\n"
            if data.get("suggested_fix"):
                body += f"## Suggested fix\n\n{data['suggested_fix']}\n\n"
            if data.get("severity"):
                body += f"**Severity:** {data['severity']}\n"

            return self.create_github_issue(title, body, labels)
        return None

    async def _execute_triage_actions(self, content: str) -> list[str]:
        """Parse LLM output for triage actions and execute bash tools."""
        import re
        results = []

        # Find JSON arrays in the output
        json_blocks = re.findall(r'```(?:json)?\s*(\[.+?\])\s*```', content, re.DOTALL)
        if not json_blocks:
            # Try inline JSON array
            json_blocks = re.findall(r'\[\s*\{[^]]+\}\s*\]', content, re.DOTALL)

        for block in json_blocks:
            try:
                actions = json.loads(block)
                if not isinstance(actions, list):
                    continue
                for action in actions:
                    if not isinstance(action, dict):
                        continue
                    act = action.get("action", "")
                    number = action.get("number")
                    if not number:
                        continue

                    if act == "close":
                        reason = action.get("reason", "triage: gesloten")
                        result = await self._run_bash_tool("close_issue", {"number": str(number), "reason": reason})
                        results.append(f"❌ #{number} gesloten: {reason}")

                    elif act == "comment":
                        comment = action.get("comment", action.get("reason", ""))
                        result = await self._run_bash_tool("comment_issue", {"number": str(number), "comment": comment})
                        results.append(f"💬 #{number} comment geplaatst")

                    elif act == "label":
                        label = action.get("label", action.get("labels_added", ["triaged"])[0] if action.get("labels_added") else "triaged")
                        result = await self._run_bash_tool("label_issue", {"number": str(number), "label": label})
                        results.append(f"🏷️ #{number} gelabeled: {label}")

                    elif act == "keep":
                        # Add acceptance criteria if provided
                        if action.get("criteria_added") or action.get("acceptatie_criteria"):
                            criteria = action.get("acceptatie_criteria", action.get("criteria", ""))
                            if criteria:
                                result = await self._run_bash_tool("comment_issue", {"number": str(number), "comment": criteria})
                                results.append(f"✅ #{number} acceptatie criteria toegevoegd")
                        # Add labels
                        for label in action.get("labels_added", []):
                            result = await self._run_bash_tool("label_issue", {"number": str(number), "label": label})
                            results.append(f"🏷️ #{number} gelabeled: {label}")

                    elif act == "analyzed":
                        root_cause = action.get("root_cause", "")
                        files = ", ".join(action.get("files", []))
                        fix = action.get("fix_proposed", False)
                        comment = f"🔍 **Solver analyse**\n\n"
                        comment += f"**Root cause:** {root_cause}\n"
                        if files:
                            comment += f"**Bestanden:** {files}\n"
                        if fix:
                            comment += f"**Fix voorgesteld:** {action.get('fix_description', '')}\n"
                        result = await self._run_bash_tool("comment_issue", {"number": str(number), "comment": comment})
                        results.append(f"🔍 #{number} geanalyseerd")

                    elif act == "needs_info":
                        questions = action.get("questions", action.get("reason", "Meer informatie nodig"))
                        comment = f"❓ **Solver heeft meer informatie nodig:**\n\n{questions}"
                        result = await self._run_bash_tool("comment_issue", {"number": str(number), "comment": comment})
                        results.append(f"❓ #{number} meer info gevraagd")

            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.debug("Triage action failed: %s", e)

        return results

    async def _run_bash_tool(self, tool_name: str, variables: dict) -> str:
        """Run a named bash tool with variables."""
        for tool in self._tools:
            if isinstance(tool, dict) and tool.get("name") == tool_name:
                # Substitute variables in command
                command = tool.get("command", "")
                for key, value in variables.items():
                    command = command.replace(f"{{{key}}}", str(value))
                # Also substitute standard variables
                command = command.replace("{vault_path}", str(self.config.vault_path))
                command = command.replace("{project_path}", str(Path.home() / "projects" / "mindlens"))
                # Execute
                tool_copy = dict(tool)
                tool_copy["command"] = command
                return await self._execute_bash_tool(tool_copy, AgentContext(task=""))
        return ""

    async def _gather_tool_data(self, context: AgentContext) -> str:
        """Gather data from configured tools."""
        data_parts = []

        for tool in self._tools:
            try:
                if isinstance(tool, dict):
                    name = tool.get("name", "bash")
                    result = await self._execute_bash_tool(tool, context)
                else:
                    name = tool
                    result = await self._execute_tool(tool, context)
                if result:
                    data_parts.append(f"### {name}\n{result}")
            except Exception as e:
                logger.debug("Tool %s failed: %s", tool, e)

        return "\n\n".join(data_parts) if data_parts else ""

    async def _agentic_loop(
        self, system_prompt: str, user_message: str, context: AgentContext, max_steps: int = 10
    ) -> tuple[str, int, int]:
        """Agentic loop using native function calling (OpenAI-compatible).
        
        LLM calls tools via API. We execute, feed results back.
        No tool calls = LLM is done.
        """
        project = str(Path.home() / "projects" / "mindlens")

        # Define the bash tool in OpenAI function calling format
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Execute a bash command and return stdout/stderr",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The bash command to execute"
                            }
                        },
                        "required": ["command"]
                    }
                }
            }
        ]

        messages = [
            {"role": "system", "content": f"{system_prompt}\n\nProject: {project}"},
            {"role": "user", "content": user_message},
        ]
        total_in, total_out = 0, 0
        last_content = ""

        for step in range(max_steps):
            response = await self.llm.complete(
                messages=messages,
                temperature=0.3,
                max_tokens=4096,
                tools=tools,
            )
            total_in += response.input_tokens
            total_out += response.output_tokens

            choice_msg = {
                "role": "assistant",
                "content": response.content,
            }
            if response.tool_calls:
                choice_msg["tool_calls"] = response.tool_calls
            messages.append(choice_msg)

            if not response.tool_calls:
                # No tool calls = done
                return response.content, total_in, total_out

            # Execute each tool call
            for tc in response.tool_calls:
                func = tc.get("function", {})
                func_name = func.get("name", "")
                import json as _json
                try:
                    args = _json.loads(func.get("arguments", "{}"))
                except _json.JSONDecodeError:
                    args = {}

                if func_name == "bash":
                    cmd = args.get("command", "")
                    try:
                        result = subprocess.run(
                            cmd, shell=True, capture_output=True,
                            text=True, timeout=30, cwd=project,
                        )
                        out = result.stdout.strip()
                        if result.returncode != 0 and result.stderr:
                            out += f"\nERR: {result.stderr.strip()[:500]}"
                        lines = (out or "(no output)").splitlines()
                        if len(lines) > 30:
                            out = "\n".join(lines[:30]) + f"\n... ({len(lines)-30} more)"
                    except subprocess.TimeoutExpired:
                        out = "(timeout 30s)"
                    except Exception as e:
                        out = f"(error: {e})"

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": out,
                    })
                else:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": f"Unknown tool: {func_name}",
                    })

            last_content = response.content

        return last_content, total_in, total_out

    async def _execute_bash_tool(self, tool_def: dict, context: AgentContext) -> str:
        """Execute a bash tool defined in YAML."""
        import subprocess
        command = tool_def.get("command", "")
        if not command:
            return ""

        # Template variables
        vault = self.config.vault_path
        project = Path.home() / 'projects' / 'mindlens'
        variables = {
            "vault_path": str(vault),
            "project_path": str(project),
            "workspace": context.workspace or "",
            "task": context.task[:200],
        }
        try:
            command = command.format(**variables)
        except KeyError:
            pass  # Leave unresolved placeholders as-is

        timeout = tool_def.get("timeout", 30)
        cwd = tool_def.get("cwd", str(project))

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True,
                text=True, timeout=timeout, cwd=cwd,
            )
            output = result.stdout.strip()
            if not output and result.stderr:
                output = f"(stderr) {result.stderr.strip()[:500]}"
            # Truncate to avoid token explosion
            max_lines = tool_def.get("max_lines", 30)
            lines_out = output.splitlines()
            if len(lines_out) > max_lines:
                output = "\n".join(lines_out[:max_lines]) + f"\n... ({len(lines_out) - max_lines} lines truncated)"
            return output or "(geen output)"
        except subprocess.TimeoutExpired:
            return "(timeout)"
        except Exception as e:
            return f"(fout: {e})"

    async def _execute_tool(self, tool_name: str, context: AgentContext) -> str:
        """Execute a built-in Python tool (DB/vault access). Bash tools handled by _execute_bash_tool."""
        vault = self.config.vault_path


        if tool_name == "list_agent_runs":
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

            return self._search_code(context)






        elif tool_name == "list_events":
            return self._list_events()

        elif tool_name == "query_agent_runs":
            return self._query_agent_runs(context)




        return ""

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

            cmd = ["gh", "issue", "create", "--title", title, "--body", body]
            if labels:
                cmd += ["--label", ",".join(labels)]

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, cwd=cwd,
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                logger.info("Created GitHub issue: %s — %s", url, title)
                return url

            # Retry without labels if they don't exist
            logger.warning("gh issue create failed (labels=%s): %s", labels, result.stderr.strip())
            if labels:
                logger.info("Retrying without labels...")
                return self.create_github_issue(title, body, [])

            logger.error("Failed to create issue: %s", result.stderr.strip())
            return None
        except Exception as e:
            logger.error("Exception creating GitHub issue: %s", e)
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
