"""Chief of Staff — Telegram interface, routing, daily briefing."""

from __future__ import annotations

import json
import logging
from typing import Any

from mindlens.agents.base import Agent, AgentContext, AgentResult
from mindlens.core.event_bus import Event

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """You are the Chief of Staff of MindLens, an AI-native holding company OS.

Your role:
- Interpret natural language requests from the user
- Route them to the correct workspace and agent
- Provide daily updates and status reports
- Manage communication between workspaces

Available workspaces:
{workspace_list}

Available agents:
- workspace_manager: Create/manage workspaces, add agents
- agent_architect: Design new agents
- agent_optimizer: Monitor performance, token tracking
- agent_librarian: Skill extraction, version control

ALWAYS respond in the same language as the user's message. Be concise and helpful.

If you can answer a question directly, do so.
If the request needs a specific agent, say: "ROUTE: agent_name | workspace | task"

IMPORTANT: If the user asks a research question (starts with "research", "how", "what", "why", "when" about a topic), route to research_intake:
"ROUTE: research_intake | Research | <the full question>"

If the user wants to create a workspace or manage agents, route to workspace_manager:
"ROUTE: workspace_manager | HQ | <the full request>"
"""


class ChiefOfStaff(Agent):
    name = "chief_of_staff"
    description = "Telegram interface, routing, daily briefing"
    capabilities = ["route", "answer", "briefing", "manage"]

    def _discover_workspaces(self) -> str:
        """Build workspace list from vault for system prompt."""
        vault = self.config.vault_path
        lines = []
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
                desc = f": {mission}" if mission else ""
                lines.append(f"- {item.name}{desc}")
        return "\n".join(lines) if lines else "- (geen workspaces gevonden)"

    def _get_system_prompt(self) -> str:
        """Build dynamic system prompt with current workspace list."""
        return SYSTEM_PROMPT_TEMPLATE.format(
            workspace_list=self._discover_workspaces()
        )

    def _load_wiki_context(self, workspace: str) -> str:
        """Load wiki page summaries for the current workspace."""
        from pathlib import Path

        wiki_dir = self.config.workspace_path(workspace) / "wiki"
        if not wiki_dir.exists():
            return ""

        pages = []
        for md_file in sorted(wiki_dir.glob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
                pages.append(f"--- {md_file.stem} ---\n{content[:500]}")
            except Exception:
                continue

        if not pages:
            return ""

        result = "\n\n".join(pages)
        if len(result) > 3000:
            result = result[:3000] + "\n...[truncated]"
        return result

    def _build_context(self, context: AgentContext) -> str:
        """Build the full context message for the LLM."""
        user_text = context.task
        workspace = context.workspace or "HQ"

        user_message = f"Workspace: [{workspace}]\nMessage: {user_text}"

        events = self.event_bus.history(limit=5)
        if events:
            event_text = "\n".join(f"- {e}" for e in events)
            user_message += f"\n\nRecent events:\n{event_text}"

        if workspace and workspace != "HQ":
            wiki_context = self._load_wiki_context(workspace)
            if wiki_context:
                user_message += f"\n\nWorkspace knowledge ({workspace}):\n{wiki_context}"

        return user_message

    async def run(self, context: AgentContext) -> AgentResult:
        """Process a user message and determine routing."""
        user_message = self._build_context(context)

        content, in_tok, out_tok = await self._llm_complete(
            self._get_system_prompt(), user_message, temperature=0.3
        )

        # Check for routing instruction
        if "ROUTE:" in content:
            parts = content.split("ROUTE:")[1].strip().split("|")
            if len(parts) >= 3:
                target_agent = parts[0].strip()
                target_workspace = parts[1].strip()
                task = parts[2].strip()

                return AgentResult(
                    success=True,
                    output=content.split("ROUTE:")[0].strip() or f"Routing to {target_agent}...",
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    events=[{
                        "topic": "agent.route",
                        "data": {
                            "target_agent": target_agent,
                            "target_workspace": target_workspace,
                            "task": task,
                        },
                    }],
                )

        return AgentResult(
            success=True,
            output=content,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )

    async def run_streaming(self, context: AgentContext):
        """Stream the response. Single LLM call for fast time to first token."""
        user_message = self._build_context(context)

        # Stream directly
        full_response = ""
        async for chunk in self.llm.stream(
            messages=[
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
        ):
            full_response += chunk
            yield chunk

        # After stream completes, check for routing instruction
        if "ROUTE:" in full_response:
            parts = full_response.split("ROUTE:")[1].strip().split("|")
            if len(parts) >= 3:
                target_agent = parts[0].strip()
                target_workspace = parts[1].strip()
                task = parts[2].strip()

                await self.event_bus.publish(Event(
                    topic="agent.route",
                    source="chief_of_staff",
                    data={
                        "target_agent": target_agent,
                        "target_workspace": target_workspace,
                        "task": task,
                    },
                ))


