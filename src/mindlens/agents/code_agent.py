"""Code Agent — minimal coding agent (pi.dev style).

Only 4 tools: bash, file_read, file_write, memory.
Everything else comes from skills that improve over time.
YAML agents can inherit these capabilities and gain more through learning.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import yaml

from mindlens.agents.base import Agent, AgentContext, AgentResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Je bent een code agent van MindLens.

Je hebt 4 tools:
1. **bash** — voer shell commando's uit
2. **file_read** — lees bestanden
3. **file_write** — schrijf naar bestanden
4. **memory** — zoek/bewaar kennis in de vault

Werkwijze:
- Lees eerst de relevante bestanden
- Begrijp de context
- Voer de taak uit
- Test het resultaat

Antwoord in het NERLANDS. Wees beknopt.
"""


class CodeAgent(Agent):
    """Minimal coding agent with 4 core tools."""

    name = "code_agent"
    description = "Minimale code agent — bash, file read/write, memory"
    capabilities = ["bash", "file_read", "file_write", "memory"]

    async def run(self, context: AgentContext) -> AgentResult:
        """Execute a coding task."""
        # Gather context from memory/skills
        memory_context = self._search_memory(context.task)

        user_message = f"Taak: {context.task}\n"
        if context.workspace:
            user_message += f"Werkruimte: {context.workspace}\n"
        if memory_context:
            user_message += f"\nRelevante kennis:\n{memory_context}"

        # Let LLM decide what to do
        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT, user_message, temperature=0.3
        )

        return AgentResult(
            success=True,
            output=content,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )

    def _search_memory(self, query: str) -> str:
        """Search vault for relevant knowledge."""
        vault = self.config.vault_path
        results = []

        # Search wiki pages
        for ws_dir in vault.iterdir():
            if ws_dir.is_dir() and not ws_dir.name.startswith("."):
                wiki_dir = ws_dir / "wiki"
                if wiki_dir.exists():
                    for md_file in wiki_dir.glob("*.md"):
                        try:
                            content = md_file.read_text()
                            if any(word.lower() in content.lower() for word in query.split()[:3]):
                                results.append(f"[{ws_dir.name}/wiki/{md_file.stem}] {content[:200]}")
                        except Exception:
                            continue

        # Search skills
        skills_dir = vault / ".mindlens" / "skills"
        if skills_dir.exists():
            for md_file in skills_dir.glob("*.md"):
                try:
                    content = md_file.read_text()
                    if any(word.lower() in content.lower() for word in query.split()[:3]):
                        results.append(f"[skill:{md_file.stem}] {content[:200]}")
                except Exception:
                    continue

        return "\n".join(results[:5]) if results else ""

    # --- Tool methods (for YAML agents to inherit) ---

    def bash(self, command: str, cwd: str | None = None, timeout: int = 30) -> str:
        """Execute a bash command."""
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=cwd,
            )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            if result.returncode != 0:
                output += f"\nEXIT CODE: {result.returncode}"
            return output[:5000]  # Truncate
        except subprocess.TimeoutExpired:
            return "TIMEOUT: Command exceeded time limit"
        except Exception as e:
            return f"ERROR: {e}"

    def file_read(self, path: str, start: int = 0, end: int = 0) -> str:
        """Read a file."""
        try:
            p = Path(path).expanduser()
            if not p.exists():
                return f"ERROR: File not found: {path}"
            content = p.read_text()
            if start or end:
                lines = content.splitlines()
                return "\n".join(lines[start:end] if end else lines[start:])
            return content[:10000]  # Truncate
        except Exception as e:
            return f"ERROR: {e}"

    def file_write(self, path: str, content: str) -> str:
        """Write to a file."""
        try:
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            return f"OK: Written {len(content)} chars to {path}"
        except Exception as e:
            return f"ERROR: {e}"

    def memory_search(self, query: str) -> str:
        """Search vault memory."""
        return self._search_memory(query)

    def memory_write(self, path: str, content: str) -> str:
        """Write to vault memory (skills, wiki, etc.)."""
        vault = self.config.vault_path
        full_path = vault / path
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            return f"OK: Written to vault/{path}"
        except Exception as e:
            return f"ERROR: {e}"


class CodeAgentYaml(CodeAgent):
    """Code agent that can be configured via YAML with additional capabilities."""

    def __init__(self, yaml_path: Path, **kwargs: Any) -> None:
        self.yaml_path = yaml_path
        self._yaml_config = yaml.safe_load(yaml_path.read_text()) or {}

        self.name = self._yaml_config.get("name", yaml_path.stem)
        self.description = self._yaml_config.get("description", "")
        self.scope = self._yaml_config.get("scope", "global")

        # Skills loaded from YAML improve the agent over time
        self._skills = self._yaml_config.get("skills", [])
        self._extra_tools = self._yaml_config.get("tools", [])

        super().__init__(**kwargs)

    async def run(self, context: AgentContext) -> AgentResult:
        """Execute with YAML-defined skills and tools."""
        # Load relevant skills
        skill_context = self._load_skills(context.task)

        # Build enhanced prompt
        system_prompt = self._yaml_config.get("system_prompt", SYSTEM_PROMPT)

        memory_context = self._search_memory(context.task)

        user_message = f"Taak: {context.task}\n"
        if context.workspace:
            user_message += f"Werkruimte: {context.workspace}\n"
        if memory_context:
            user_message += f"\nRelevante kennis:\n{memory_context}"
        if skill_context:
            user_message += f"\nVaardigheden:\n{skill_context}"

        content, in_tok, out_tok = await self._llm_complete(
            system_prompt, user_message, temperature=0.3
        )

        return AgentResult(
            success=True,
            output=content,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )

    def _load_skills(self, task: str) -> str:
        """Load relevant skills from vault."""
        vault = self.config.vault_path
        skill_parts = []

        # Global skills index
        index_path = vault / ".mindlens" / "skills" / "index.yaml"
        if index_path.exists():
            index = yaml.safe_load(index_path.read_text()) or {}
            for skill in index.get("skills") or []:
                skill_file = vault / ".mindlens" / "skills" / skill.get("path", "")
                if skill_file.exists():
                    try:
                        content = skill_file.read_text()
                        # Check relevance
                        if any(word.lower() in content.lower() for word in task.split()[:3]):
                            skill_parts.append(f"## Skill: {skill['name']}\n{content[:500]}")
                    except Exception:
                        continue

        # Workspace skills
        ws = self._yaml_config.get("scope", "")
        if ws and ws != "global":
            ws_index = vault / ws / ".mindlens" / "skills" / "index.yaml"
            if ws_index.exists():
                index = yaml.safe_load(ws_index.read_text()) or {}
                for skill in index.get("skills") or []:
                    skill_file = vault / ws / ".mindlens" / "skills" / skill.get("path", "")
                    if skill_file.exists():
                        try:
                            content = skill_file.read_text()
                            if any(word.lower() in content.lower() for word in task.split()[:3]):
                                skill_parts.append(f"## Skill: {skill['name']}\n{content[:500]}")
                        except Exception:
                            continue

        return "\n\n".join(skill_parts[:3]) if skill_parts else ""
