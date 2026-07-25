"""LLM Router — intelligent routing of user requests to appropriate agents.

This module provides a unified routing layer that:
1. Parses user intent using LLM
2. Decides which agent to route to (or answer directly)
3. Handles multi-language input (Dutch, English, etc.)
4. Supports workspace-scoped routing
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from mindlens.agents.base import AgentContext

logger = logging.getLogger(__name__)


class RouteAction(Enum):
    """Possible routing actions."""
    ANSWER = "answer"           # Answer directly without routing
    ROUTE = "route"             # Route to a specific agent
    CLARIFY = "clarify"         # Ask for clarification
    UNKNOWN = "unknown"         # Could not determine intent


@dataclass
class RouteDecision:
    """Decision made by the router."""
    action: RouteAction
    target_agent: str | None = None
    target_workspace: str | None = None
    task: str | None = None
    response: str | None = None
    confidence: float = 0.0


ROUTER_SYSTEM_PROMPT = """You are an intelligent request router for MindLens, an AI-native holding company OS.

Your job is to analyze user messages and determine the best action.

## Available Agents

- **workspace_manager**: Create/manage workspaces, add agents to workspaces
- **agent_architect**: Design new agents, generate prompts
- **agent_optimizer**: Monitor performance, track tokens
- **agent_librarian**: Skill extraction, version control
- **research_intake**: Process research questions, create research notes
- **code_agent**: Execute coding tasks (bash, file read/write)

## Available Workspaces

{workspace_list}

## Routing Rules

1. **Direct answer**: Simple questions, greetings, status checks, general knowledge
2. **Route to agent**: Tasks that require specific agent capabilities
3. **Clarify**: Ambiguous requests that could go multiple ways

## Response Format

ALWAYS respond with a JSON object:
{{
    "action": "answer" | "route" | "clarify",
    "target_agent": "agent_name or null",
    "target_workspace": "workspace_name or null (default: HQ)",
    "task": "the task for the agent (only for route action)",
    "response": "direct answer to the user (only for answer action)",
    "confidence": 0.0-1.0
}}

## Examples

User: "Hello, how are you?"
→ {{"action": "answer", "response": "Hello! I'm doing well. How can I help you today?", "confidence": 0.95}}

User: "Create workspace Persoonlijk"
→ {{"action": "route", "target_agent": "workspace_manager", "target_workspace": "HQ", "task": "Create workspace Persoonlijk", "confidence": 0.9}}

User: "Maak nieuwe workspace aan met naam 'Persoonlijk' en type 'personal'"
→ {{"action": "route", "target_agent": "workspace_manager", "target_workspace": "HQ", "task": "Maak nieuwe workspace aan met naam 'Persoonlijk' en type 'personal'", "confidence": 0.9}}

User: "What workspaces exist?"
→ {{"action": "route", "target_agent": "workspace_manager", "target_workspace": "HQ", "task": "List all workspaces", "confidence": 0.95}}

User: "Research the latest AI trends"
→ {{"action": "route", "target_agent": "research_intake", "target_workspace": "Research", "task": "Research the latest AI trends", "confidence": 0.85}}

User: "Fix the bug in the login system"
→ {{"action": "route", "target_agent": "code_agent", "target_workspace": "HQ", "task": "Fix the bug in the login system", "confidence": 0.8}}

User: "Hoe gaat het?"
→ {{"action": "answer", "response": "Het gaat goed! Hoe kan ik je helpen?", "confidence": 0.95}}

User: "Wat zijn de beschikbare workspaces?"
→ {{"action": "route", "target_agent": "workspace_manager", "target_workspace": "HQ", "task": "List all workspaces", "confidence": 0.95}}

Always respond in the same language as the user's message.
"""


class LLMRouter:
    """Intelligent router that uses LLM to determine routing decisions."""

    def __init__(self, llm: Any, config: Any) -> None:
        self.llm = llm
        self.config = config

    def _get_workspace_list(self) -> str:
        """Build workspace list from vault."""
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
        return "\n".join(lines) if lines else "- (no workspaces found)"

    async def route(self, context: AgentContext) -> RouteDecision:
        """Determine the best routing decision for a user message."""
        workspace_list = self._get_workspace_list()
        system_prompt = ROUTER_SYSTEM_PROMPT.format(workspace_list=workspace_list)

        user_message = f"User message: {context.task}\n"
        if context.workspace:
            user_message += f"Current workspace: {context.workspace}\n"

        try:
            response = await self.llm.complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,
            )
            content = response.content

            # Parse JSON response — handle markdown code blocks
            json_str = content
            if "```" in content:
                # Extract content between ``` markers
                import re
                match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', content, re.DOTALL)
                if match:
                    json_str = match.group(1).strip()
            elif not content.strip().startswith("{"):
                # Try to find JSON object in the response
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end != -1:
                    json_str = content[start:end + 1]

            data = json.loads(json_str)

            action_str = data.get("action", "unknown")
            try:
                action = RouteAction(action_str)
            except ValueError:
                action = RouteAction.UNKNOWN

            return RouteDecision(
                action=action,
                target_agent=data.get("target_agent"),
                target_workspace=data.get("target_workspace", "HQ"),
                task=data.get("task"),
                response=data.get("response"),
                confidence=data.get("confidence", 0.0),
            )

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Router failed to parse LLM response: %s", e)
            # Fallback: try to answer directly
            return RouteDecision(
                action=RouteAction.ANSWER,
                response=content if 'content' in dir() else "I'm not sure how to help with that. Could you rephrase?",
                confidence=0.3,
            )
        except Exception as e:
            logger.exception("Router error: %s", e)
            return RouteDecision(
                action=RouteAction.ANSWER,
                response="I encountered an error processing your request. Please try again.",
                confidence=0.0,
            )
