"""Bug Hunter — automatically finds bugs and creates GitHub issues."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import aiosqlite

from mindlens.agents.base import Agent, AgentContext, AgentResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Bug Hunter of MindLens Cortex.

You automatically search for bugs in the system by:
1. Analyzing agent runs for repeated errors
2. Scanning VS Code sessions for error patterns
3. Checking code for common issues

For each bug found, provide:
- Title (short, descriptive)
- Description (what's wrong, how to reproduce)
- Severity (low/medium/high/critical)
- Suggested fix (if you can determine one)

Always respond in the same language as the user's message with a JSON array of bugs:
[
    {
        "title": "bug title",
        "description": "detailed description",
        "severity": "high",
        "labels": ["bug", "auto-detected"],
        "suggested_fix": "how to fix"
    }
]
"""


class BugHunter(Agent):
    name = "bug_hunter"
    description = "Automatic bug detection and GitHub issue creation"
    scope = "global"

    async def run(self, context: AgentContext) -> AgentResult:
        task = context.task.lower()

        if "github" in task or "issue" in task:
            return await self._hunt_and_create_issues()
        elif "scan" in task or "search" in task:
            return await self._scan_for_bugs()
        else:
            return await self._hunt_and_create_issues()

    async def _scan_for_bugs(self) -> AgentResult:
        """Scan for bugs without creating issues."""
        findings = await self._gather_findings()

        if not findings:
            return AgentResult(success=True, output="✅ No bugs found in recent data.")

        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Analyze these findings and identify bugs:\n\n{findings}",
            temperature=0.2,
        )

        return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)

    async def _hunt_and_create_issues(self) -> AgentResult:
        """Scan for bugs and create GitHub issues."""
        findings = await self._gather_findings()

        if not findings:
            return AgentResult(success=True, output="✅ No bugs found.")

        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Analyze these findings and identify bugs. Return a JSON array:\n\n{findings}",
            temperature=0.2,
        )

        # Parse bugs from response
        cleaned = self._strip_code_fences(content)
        try:
            bugs = json.loads(cleaned)
        except json.JSONDecodeError:
            return AgentResult(
                success=True,
                output=f"Bugs found but not structured:\n\n{content[:500]}",
                input_tokens=in_tok,
                output_tokens=out_tok,
            )

        if not isinstance(bugs, list):
            bugs = [bugs]

        # Create GitHub issues
        created = []
        for bug in bugs:
            title = bug.get("title", "Auto-detected bug")
            description = bug.get("description", "")
            severity = bug.get("severity", "medium")
            labels = bug.get("labels", ["bug", "auto-detected"])
            suggested_fix = bug.get("suggested_fix", "")

            body = f"## Bug (auto-detected door Cortex Bug Hunter)\n\n{description}\n\n"
            if suggested_fix:
                body += f"## Suggested fix\n\n{suggested_fix}\n\n"
            body += f"**Severity:** {severity}\n"
            body += f"**Gedetecteerd:** automatisch\n"

            issue_url = self._create_github_issue(title, body, labels)
            if issue_url:
                created.append(f"✅ [{title}]({issue_url})")
            else:
                created.append(f"❌ {title} (aanmaken mislukt)")

        output = f"🐛 Bug Hunter Resultaat:\n\n"
        output += f"**{len(created)} bugs gevonden en verwerkt:**\n\n"
        for c in created:
            output += f"  {c}\n"

        return AgentResult(success=True, output=output, input_tokens=in_tok, output_tokens=out_tok)

    async def _gather_findings(self) -> str:
        """Gather data from multiple sources for bug detection."""
        findings = []

        # 1. Check agent_runs for failures
        try:
            conn = await aiosqlite.connect(str(self.config.core_db_path))
            cursor = await conn.execute("""
                SELECT agent_name, workspace, task_description, success, duration_seconds
                FROM agent_runs
                WHERE created_at >= DATE('now', '-2 days')
                AND success = 0
                ORDER BY created_at DESC
                LIMIT 20
            """)
            failures = await cursor.fetchall()
            await conn.close()

            if failures:
                findings.append("## Agent Failures (last 2 days)\n")
                for agent, ws, task, success, duration in failures:
                    findings.append(f"- ❌ {agent} [{ws}]: {(task or '')[:80]} ({duration:.1f}s)")
        except Exception:
            pass

        # 2. Check VS Code sessions for error patterns
        sessions_dir = self.config.copilot_transcripts_path
        if sessions_dir.exists():
            import re
            error_counts = {}
            for f in sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                try:
                    content = f.read_text()
                    errors = re.findall(r'"error[^"]*"[^}]*"message[^"]*"([^"]{10,80})"', content)
                    for err in errors:
                        key = err[:50]
                        error_counts[key] = error_counts.get(key, 0) + 1
                except Exception:
                    continue

            if error_counts:
                findings.append("\n## VS Code Session Errors\n")
                for err, count in sorted(error_counts.items(), key=lambda x: -x[1])[:10]:
                    if count > 1:
                        findings.append(f"- {count}x: {err}")

        # 3. Check for high token usage (potential waste)
        try:
            conn = await aiosqlite.connect(str(self.config.core_db_path))
            cursor = await conn.execute("""
                SELECT agent_name, workspace, task_description,
                       input_tokens + output_tokens as total_tokens, cost_usd
                FROM agent_runs
                WHERE created_at >= DATE('now', '-1 day')
                AND (input_tokens + output_tokens) > 5000
                ORDER BY cost_usd DESC
                LIMIT 5
            """)
            expensive = await cursor.fetchall()
            await conn.close()

            if expensive:
                findings.append("\n## High Token Usage (potential waste)\n")
                for agent, ws, task, tokens, cost in expensive:
                    findings.append(f"- {agent} [{ws}]: {tokens} tokens (${cost:.4f}) — {(task or '')[:60]}")
        except Exception:
            pass

        return "\n".join(findings) if findings else ""

    def _create_github_issue(self, title: str, body: str, labels: list[str]) -> str | None:
        """Create a GitHub issue using gh CLI."""
        try:
            result = subprocess.run(
                ["gh", "issue", "create",
                 "--title", title,
                 "--body", body,
                 "--label", ",".join(labels)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.config.project_path),
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                logger.info("Created GitHub issue: %s", url)
                return url
            else:
                logger.error("Failed to create issue: %s", result.stderr)
                return None
        except Exception as e:
            logger.error("Failed to create issue: %s", e)
            return None
