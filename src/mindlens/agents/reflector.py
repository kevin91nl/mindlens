"""Reflector — deep reflection on system health, generates improvement proposals."""

from __future__ import annotations

import json
import logging

from mindlens.agents.base import Agent, AgentContext, AgentResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Je bent de Reflector van MindLens Cortex.

Je doet diepe reflectie op het hele MindLens systeem. Je identificeert:
1. Wat werkt goed en waarom
2. Wat werkt niet en waarom
3. Welke patronen je ziet
4. Concrete verbetervoorstellen met verwachte impact

Antwoord in het Nederlands. Wees specifiek en meetbaar.
"""


class Reflector(Agent):
    name = "reflector"
    description = "Diepe reflectie, verbetervoorstellen, patroonherkenning"
    scope = "global"

    async def run(self, context: AgentContext) -> AgentResult:
        task = context.task.lower()

        # Gather system-wide data
        data = await self._gather_system_data()

        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Reflecteer op de huidige staat van MindLens:\n\n{data}\n\nVraag: {context.task}",
            temperature=0.4,
        )

        return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)

    async def _gather_system_data(self) -> str:
        """Gather data from across the system for reflection."""
        data = []

        # Workspace overview
        vault = self.config.vault_path
        workspaces = [d.name for d in vault.iterdir() if d.is_dir() and not d.name.startswith(".")]
        data.append(f"Workspaces: {', '.join(workspaces)}")

        # Global skills
        skills_path = vault / ".mindlens" / "skills" / "index.yaml"
        if skills_path.exists():
            import yaml
            skills = yaml.safe_load(skills_path.read_text()) or {}
            skill_list = skills.get("skills") or []
            data.append(f"Global skills: {len(skill_list)}")
            for s in skill_list[:5]:
                data.append(f"  - {s.get('name', '?')}: used {s.get('useful_count', 0)}x")

        # Issues overview
        for ws in workspaces:
            issues_path = vault / ws / "issues.yaml"
            if issues_path.exists():
                import yaml
                issues = yaml.safe_load(issues_path.read_text()) or {}
                issue_list = issues.get("issues") or []
                open_issues = [i for i in issue_list if i.get("status") not in ("done",)]
                if open_issues:
                    data.append(f"{ws} open issues: {len(open_issues)}")

        # Recent events
        events = self.event_bus.history(limit=10)
        if events:
            data.append(f"Recent events: {len(events)}")
            for e in events[-5:]:
                data.append(f"  - {e}")

        return "\n".join(data) if data else "Geen data beschikbaar."
