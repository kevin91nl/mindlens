"""Memory Manager — extracts lessons from tasks, manages skill lifecycle."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from mindlens.agents.base import Agent, AgentContext, AgentResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Je bent de Memory Manager van MindLens Cortex.

Je taken:
1. Extraheer lessen uit afgeronde taken
2. Beheer de skill levenscyclus (aanmaken, bijwerken, archiveren)
3. Identificeer verouderde of ineffectieve skills
4. Zorg dat kennis niet verloren gaat

Antwoord in het Nederlands.
"""


class MemoryManager(Agent):
    name = "memory_manager"
    description = "Skill extractie, levenscyclus beheer, kennispreservatie"
    scope = "global"

    async def run(self, context: AgentContext) -> AgentResult:
        task = context.task.lower()

        if "extract" in task or "extraheer" in task:
            return await self._extract_skill(context)
        elif "archive" in task or "verwijder" in task:
            return await self._archive_stale_skills()
        elif "list" in task or "overzicht" in task:
            return await self._list_all_skills()
        else:
            return await self._scan_for_extractable(context)

    async def _extract_skill(self, context: AgentContext) -> AgentResult:
        """Extract a reusable skill from a task."""
        workspace = context.workspace or "global"

        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Taak: {context.task}\n"
            f"Metadata: {json.dumps(context.metadata)}\n\n"
            f"Is dit een herbruikbaar patroon? Zo ja, genereer een skill in markdown formaat.",
            temperature=0.3,
        )

        # Save skill if it looks like one
        if "```" in content or "# " in content:
            skills_dir = self.config.global_skills_path()
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
                output=f"✅ Skill geëxtraheerd: {name}\n\n{content[:300]}",
                input_tokens=in_tok,
                output_tokens=out_tok,
            )

        return AgentResult(success=True, output="Geen herbruikbaar patroon gevonden.", input_tokens=in_tok, output_tokens=out_tok)

    async def _archive_stale_skills(self) -> AgentResult:
        """Find and archive skills that haven't been useful."""
        skills_dir = self.config.global_skills_path()
        index_path = skills_dir / "index.yaml"

        if not index_path.exists():
            return AgentResult(success=True, output="Geen skills gevonden.")

        index = yaml.safe_load(index_path.read_text()) or {"skills": []}
        skills = index.get("skills") or []

        stale = [s for s in skills if s.get("useful_count", 0) == 0 and s.get("last_used")]

        if not stale:
            return AgentResult(success=True, output="Alle skills zijn recent gebruikt of nieuw.")

        output = "📦 Skills om te archiveren (0x gebruikt):\n"
        for s in stale:
            output += f"  • {s['name']}: {s.get('description', '?')[:60]}\n"

        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Beoordeel deze ongebruikte skills. Moeten ze gearchiveerd worden?\n\n{output}",
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
            return AgentResult(success=True, output="Geen skills gevonden in het systeem.")

        output = f"🧠 Skills overzicht ({len(all_skills)} totaal):\n\n" + "\n".join(all_skills)
        return AgentResult(success=True, output=output)

    async def _scan_for_extractable(self, context: AgentContext) -> AgentResult:
        """Scan recent agent runs for extractable patterns."""
        import aiosqlite

        try:
            conn = await aiosqlite.connect(str(self.config.core_db_path()))
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
                return AgentResult(success=True, output="Geen recente runs om te analyseren.")

            runs = []
            for agent, ws, task, success, duration in rows:
                runs.append(f"{'✅' if success else '❌'} {agent} [{ws}]: {(task or '')[:80]} ({duration:.1f}s)")

            content, in_tok, out_tok = await self._llm_complete(
                SYSTEM_PROMPT,
                f"Analyseer deze recente taken en identificeer welke een skill zouden moeten opleveren:\n\n" + "\n".join(runs),
                temperature=0.3,
            )

            return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)

        except Exception as e:
            return AgentResult(success=False, output=f"Fout: {e}")
