"""Chief of Staff — Telegram interface, routing, daily briefing."""

from __future__ import annotations

import json
import logging
from typing import Any

from mindlens.agents.base import Agent, AgentContext, AgentResult
from mindlens.core.event_bus import Event

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Je bent de Chief of Staff van MindLens, een AI-native holding company OS.

Jouw rol:
- Interpret natuurlijke taalverzoeken van de gebruiker
- Routeer ze naar de juiste workspace en agent
- Geef dagelijkse updates en statusrapporten
- Beheer communicatie tussen workspaces

Beschikbare workspaces:
- Research: Onderzoek & kennisdistillatie (raw → wiki pipeline)
- Tuvia: AI-gedreven businessontwikkeling
- RiskStudio: Architectuurdocs & kwaliteitsbewaking

Beschikbare agents:
- workspace_manager: Workspaces aanmaken/beheren
- agent_architect: Nieuwe agents ontwerpen
- agent_optimizer: Prestaties monitoren, token-tracking
- agent_librarian: Skill-extractie, versiebeheer

Antwoord ALTIJD in het Nederlands. Wees beknopt en behulpzaam.

Als je een vraag direct kunt beantwoorden, doe dat dan gewoon.
Als het verzoek een specifieke agent nodig heeft, zeg dan: "ROUTE: agent_naam | workspace | taak"

BELANGRIJK: Als de gebruiker een onderzoeksvraag stelt (begint met "onderzoek", "hoe", "wat", "waarom", "wanneer" over een onderwerp), routeer dan naar research_intake:
"ROUTE: research_intake | Research | <de volledige vraag>"
"""


class ChiefOfStaff(Agent):
    name = "chief_of_staff"
    description = "Telegram interface, routing, daily briefing"
    capabilities = ["route", "answer", "briefing", "manage"]

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

        user_message = f"Werkruimte: [{workspace}]\nBericht: {user_text}"

        events = self.event_bus.history(limit=5)
        if events:
            event_text = "\n".join(f"- {e}" for e in events)
            user_message += f"\n\nRecente events:\n{event_text}"

        if workspace and workspace != "HQ":
            wiki_context = self._load_wiki_context(workspace)
            if wiki_context:
                user_message += f"\n\nWerkruimte kennis ({workspace}):\n{wiki_context}"

        return user_message

    async def run(self, context: AgentContext) -> AgentResult:
        """Process a user message and determine routing."""
        user_message = self._build_context(context)

        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT, user_message, temperature=0.3
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
                    output=content.split("ROUTE:")[0].strip() or f"Routeren naar {target_agent}...",
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
                {"role": "system", "content": SYSTEM_PROMPT},
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


