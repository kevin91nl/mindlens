"""Memory Manager — extracts lessons from tasks, manages skill lifecycle."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from mindlens.agents.base import Agent, AgentContext, AgentResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Memory Manager of MindLens Cortex.

Your tasks:
1. Extract lessons from completed tasks
2. Manage the skill lifecycle (create, update, archive)
3. Identify outdated or ineffective skills
4. Ensure knowledge is not lost

Always respond in the same language as the user's message.
"""


class MemoryManager(Agent):
    name = "memory_manager"
    description = "Skill extraction, lifecycle management, knowledge preservation"
    scope = "global"

    async def run(self, context: AgentContext) -> AgentResult:
        task = context.task.lower()

        if "extract" in task:
            return await self._extract_skill(context)
        elif "archive" in task or "remove" in task:
            return await self._archive_stale_skills()
        elif "list" in task or "overview" in task:
            return await self._list_all_skills()
        else:
            return await self._scan_for_extractable(context)

    async def _extract_skill(self, context: AgentContext) -> AgentResult:
        """Extract a reusable skill from a task."""
        workspace = context.workspace or "global"

        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Task: {context.task}\n"
            f"Metadata: {json.dumps(context.metadata)}\n\n"
            f"Is this a reusable pattern? If so, generate a skill in markdown format.",
            temperature=0.3,
        )

        # Save skill if it looks like one
        if "```" in content or "# " in content:
            skills_dir = self.config.global_skills_path
            skills_dir.mkdir(parents=True, exist_ok=True)

            # Generate name from content
            name = "extracted-skill-" + datetime.now().strftime("%Y%m%d-%H%M")
            skill_path = skills_dir / f"{name}.md"
            skill_path.write_text(content)

            # Update index
            index_path = skills_dir / "index.yaml"
            index = {"skills": []}
            if index_path.exists():
                index = yaml.safe_load(index_path.read_text()) or {"skills": []}

            index["skills"].append({
                "name": name,
                "description": content[:100].split("\n")[0],
                "path": f"{name}.md",
                "tokens": len(content.split()) * 2,
                "useful_count": 0,
                "last_used": datetime.now(timezone.utc).isoformat(),
            })
            index_path.write_text(yaml.dump(index, default_flow_style=False))

            return AgentResult(
                success=True,
                output=f"✅ Skill extracted: {name}\n\n{content[:300]}",
                input_tokens=in_tok,
                output_tokens=out_tok,
            )

        return AgentResult(success=True, output="No reusable pattern found.", input_tokens=in_tok, output_tokens=out_tok)

    async def _archive_stale_skills(self) -> AgentResult:
        """Find and archive skills that haven't been useful."""
        skills_dir = self.config.global_skills_path
        index_path = skills_dir / "index.yaml"

        if not index_path.exists():
            return AgentResult(success=True, output="No skills found.")

        index = yaml.safe_load(index_path.read_text()) or {"skills": []}
        skills = index.get("skills") or []

        stale = [s for s in skills if s.get("useful_count", 0) == 0 and s.get("last_used")]

        if not stale:
            return AgentResult(success=True, output="All skills have been recently used or are new.")

        output = "📦 Skills to archive (0x used):\n"
        for s in stale:
            output += f"  • {s['name']}: {s.get('description', '?')[:60]}\n"

        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Review these unused skills. Should they be archived?\n\n{output}",
            temperature=0.2,
        )

        return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)

    async def _list_all_skills(self) -> AgentResult:
        """List all skills across all workspaces."""
        vault = self.config.vault_path
        all_skills = []

        # Global
        global_index = vault / ".mindlens" / "skills" / "index.yaml"
        if global_index.exists():
            index = yaml.safe_load(global_index.read_text()) or {"skills": []}
            for s in index.get("skills") or []:
                all_skills.append(f"🌐 {s.get('name', '?')}: {s.get('description', '?')[:60]}")

        # Per workspace
        for item in vault.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                ws_index = item / ".mindlens" / "skills" / "index.yaml"
                if ws_index.exists():
                    index = yaml.safe_load(ws_index.read_text()) or {"skills": []}
                    for s in index.get("skills") or []:
                        all_skills.append(f"📁 [{item.name}] {s.get('name', '?')}: {s.get('description', '?')[:60]}")

        if not all_skills:
            return AgentResult(success=True, output="No skills found in the system.")

        output = f"🧠 Skills overview ({len(all_skills)} total):\n\n" + "\n".join(all_skills)
        return AgentResult(success=True, output=output)

    async def _scan_for_extractable(self, context: AgentContext) -> AgentResult:
        """Scan recent agent runs for extractable patterns."""
        import aiosqlite

        try:
            conn = await aiosqlite.connect(str(self.config.core_db_path))
            cursor = await conn.execute("""
                SELECT agent_name, workspace, task_description, success, duration_seconds
                FROM agent_runs
                WHERE created_at >= DATE('now', '-1 day')
                ORDER BY created_at DESC
                LIMIT 20
            """)
            rows = await cursor.fetchall()
            await conn.close()

            if not rows:
                return AgentResult(success=True, output="No recent runs to analyze.")

            runs = []
            for agent, ws, task, success, duration in rows:
                runs.append(f"{'✅' if success else '❌'} {agent} [{ws}]: {(task or '')[:80]} ({duration:.1f}s)")

            content, in_tok, out_tok = await self._llm_complete(
                SYSTEM_PROMPT,
                f"Analyze these recent tasks and identify which should yield a skill:\n\n" + "\n".join(runs),
                temperature=0.3,
            )

            return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)

        except Exception as e:
            return AgentResult(success=False, output=f"Error: {e}")
