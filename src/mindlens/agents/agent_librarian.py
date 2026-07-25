"""Agent Librarian — version control for agent configs, skill extraction."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from mindlens.agents.base import Agent, AgentContext, AgentResult
from mindlens.core.event_bus import Event

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Agent Librarian for MindLens.

Your job after every completed task is to analyze what happened and extract reusable knowledge.

Given a task description, its result, and any errors encountered, determine:
1. Did we learn anything reusable?
2. Is it a pattern, pitfall, shortcut, or procedure?
3. Should it be a new skill or an update to an existing one?

Respond with JSON:
{
    "should_extract": true/false,
    "skill_name": "name-of-skill",
    "skill_description": "one-line description",
    "skill_content": "full markdown content of the skill",
    "is_update": false,
    "update_target": null
}
"""


class AgentLibrarian(Agent):
    name = "agent_librarian"
    description = "Version control for agent configs, skill extraction from tasks"
    capabilities = ["extract_skill", "list_skills", "version_agent"]

    async def run(self, context: AgentContext) -> AgentResult:
        """Extract skills from completed tasks or manage agent versions."""
        task = context.task.lower()

        if "extract" in task or "learn" in task:
            return await self._extract_skill(context)
        elif "list" in task and "skill" in task:
            return await self._list_skills(context)
        else:
            return await self._extract_skill(context)

    async def _extract_skill(self, context: AgentContext) -> AgentResult:
        """Analyze a task and extract a reusable skill if applicable."""
        workspace = context.workspace

        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Task: {context.task}\n"
            f"Workspace: {workspace or 'global'}\n"
            f"Metadata: {json.dumps(context.metadata)}",
            temperature=0.3,
        )

        try:
            extraction = json.loads(self._strip_code_fences(content))
        except json.JSONDecodeError:
            return AgentResult(
                success=False,
                output=f"Could not parse extraction: {content}",
                input_tokens=in_tok,
                output_tokens=out_tok,
            )

        if not extraction.get("should_extract"):
            return AgentResult(
                success=True,
                output="Nothing reusable extracted from this task.",
                input_tokens=in_tok,
                output_tokens=out_tok,
            )

        skill_name = extraction["skill_name"]
        skill_desc = extraction["skill_description"]
        skill_content = extraction["skill_content"]

        # Determine where to save the skill
        if workspace:
            skills_dir = self.config.workspace_path(workspace) / ".mindlens" / "skills"
        else:
            skills_dir = self.config.global_skills_path

        skills_dir.mkdir(parents=True, exist_ok=True)

        # Write skill file
        skill_file = skills_dir / f"{skill_name}.md"
        skill_file.write_text(skill_content)

        # Update index
        index_file = skills_dir / "index.yaml"
        if index_file.exists():
            index = yaml.safe_load(index_file.read_text()) or {"skills": []}
        else:
            index = {"skills": []}

        # Check if skill already exists in index
        existing = [s for s in index["skills"] if s.get("name") == skill_name]
        if existing:
            existing[0]["description"] = skill_desc
            existing[0]["last_used"] = datetime.now(timezone.utc).isoformat()
            existing[0]["useful_count"] = existing[0].get("useful_count", 0) + 1
        else:
            index["skills"].append({
                "name": skill_name,
                "description": skill_desc,
                "path": f"{skill_name}.md",
                "tokens": len(skill_content.split()) * 2,  # rough estimate
                "useful_count": 1,
                "last_used": datetime.now(timezone.utc).isoformat(),
            })

        index_file.write_text(yaml.dump(index, default_flow_style=False))

        await self.event_bus.publish(Event(
            topic="skill.extracted",
            source="agent_librarian",
            data={"skill": skill_name, "workspace": workspace or "global"},
        ))

        return AgentResult(
            success=True,
            output=(
                f"✅ Skill extracted: '{skill_name}'\n"
                f"  Description: {skill_desc}\n"
                f"  Saved to: {skill_file}\n"
                f"  {'Updated' if existing else 'Added to'} index"
            ),
            input_tokens=in_tok,
            output_tokens=out_tok,
        )

    async def _list_skills(self, context: AgentContext) -> AgentResult:
        """List all skills for a workspace (or global)."""
        workspace = context.workspace

        # Collect global + workspace skills
        all_skills = []

        # Global
        global_index = self.config.global_skills_path / "index.yaml"
        if global_index.exists():
            index = yaml.safe_load(global_index.read_text()) or {"skills": []}
            for s in index.get("skills", []):
                all_skills.append({**s, "scope": "global"})

        # Workspace
        if workspace:
            ws_index = self.config.workspace_path(workspace) / ".mindlens" / "skills" / "index.yaml"
            if ws_index.exists():
                index = yaml.safe_load(ws_index.read_text()) or {"skills": []}
                for s in index.get("skills", []):
                    all_skills.append({**s, "scope": workspace})

        if not all_skills:
            return AgentResult(success=True, output="No skills found.")

        output = "📚 Skills:\n\n"
        for s in all_skills:
            output += f"• [{s['scope']}] {s['name']} — {s.get('description', '?')}\n"

        return AgentResult(success=True, output=output)
