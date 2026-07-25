"""Agent Optimizer — monitors performance, tracks tokens, suggests improvements."""

from __future__ import annotations

import json
import logging

import aiosqlite

from mindlens.agents.base import Agent, AgentContext, AgentResult

logger = logging.getLogger(__name__)


class AgentOptimizer(Agent):
    name = "agent_optimizer"
    description = "Monitors agent performance, tracks tokens, suggests improvements"
    capabilities = ["performance_report", "suggest_improvements", "token_analysis"]

    async def run(self, context: AgentContext) -> AgentResult:
        """Analyze agent performance and suggest improvements."""
        task = context.task.lower()

        if "performance" in task or "report" in task:
            return await self._performance_report()
        elif "token" in task or "cost" in task:
            return await self._token_analysis()
        elif "improve" in task or "suggest" in task:
            return await self._suggest_improvements()
        else:
            return await self._performance_report()

    async def _performance_report(self) -> AgentResult:
        """Generate a performance report from agent_runs table."""
        try:
            conn = await aiosqlite.connect(str(self.config.core_db_path()))
            cursor = await conn.execute(
                """SELECT agent_name, workspace,
                          COUNT(*) as runs,
                          SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes,
                          SUM(input_tokens) as total_in,
                          SUM(output_tokens) as total_out,
                          SUM(cost_usd) as total_cost,
                          AVG(duration_seconds) as avg_duration
                   FROM agent_runs
                   GROUP BY agent_name, workspace
                   ORDER BY runs DESC"""
            )
            rows = await cursor.fetchall()
            await conn.close()

            if not rows:
                return AgentResult(success=True, output="No agent runs recorded yet.")

            output = "📊 Agent Performance Report\n\n"
            for row in rows:
                agent, workspace, runs, successes, in_tok, out_tok, cost, duration = row
                rate = (successes / runs * 100) if runs else 0
                output += (
                    f"• **{agent}** [{workspace or 'global'}]\n"
                    f"  Runs: {runs}, Success: {rate:.0f}%, "
                    f"Tokens: {in_tok or 0}+{out_tok or 0}, "
                    f"Cost: ${cost or 0:.4f}, "
                    f"Avg: {duration or 0:.1f}s\n"
                )

            return AgentResult(success=True, output=output)

        except Exception as e:
            return AgentResult(success=False, output=f"Error: {e}")

    async def _token_analysis(self) -> AgentResult:
        """Analyze token usage patterns."""
        try:
            conn = await aiosqlite.connect(str(self.config.core_db_path()))
            cursor = await conn.execute(
                """SELECT DATE(created_at) as day,
                          SUM(input_tokens) as in_tok,
                          SUM(output_tokens) as out_tok,
                          SUM(cost_usd) as cost
                   FROM agent_runs
                   GROUP BY day
                   ORDER BY day DESC
                   LIMIT 7"""
            )
            rows = await cursor.fetchall()
            await conn.close()

            if not rows:
                return AgentResult(success=True, output="No token data yet.")

            output = "📈 Token Usage (last 7 days)\n\n"
            total_cost = 0
            for day, in_tok, out_tok, cost in rows:
                total_cost += cost or 0
                output += f"• {day}: {in_tok or 0}+{out_tok or 0} tokens, ${cost or 0:.4f}\n"
            output += f"\nTotal: ${total_cost:.4f}"

            return AgentResult(success=True, output=output)

        except Exception as e:
            return AgentResult(success=False, output=f"Error: {e}")

    async def _suggest_improvements(self) -> AgentResult:
        """Analyze patterns and suggest improvements."""
        try:
            conn = await aiosqlite.connect(str(self.config.core_db_path()))
            cursor = await conn.execute(
                """SELECT agent_name, skills_loaded, skills_useful, success
                   FROM agent_runs
                   ORDER BY created_at DESC
                   LIMIT 20"""
            )
            rows = await cursor.fetchall()
            await conn.close()

            if not rows:
                return AgentResult(success=True, output="Not enough data for suggestions.")

            # Analyze skill usage
            skill_load_count: dict[str, int] = {}
            skill_useful_count: dict[str, int] = {}
            failures = 0

            for agent, loaded, useful, success in rows:
                for s in json.loads(loaded or "[]"):
                    skill_load_count[s] = skill_load_count.get(s, 0) + 1
                for s in json.loads(useful or "[]"):
                    skill_useful_count[s] = skill_useful_count.get(s, 0) + 1
                if not success:
                    failures += 1

            output = "💡 Improvement Suggestions\n\n"

            # Skills that are loaded but never useful
            for skill, loads in skill_load_count.items():
                useful = skill_useful_count.get(skill, 0)
                if loads > 3 and useful == 0:
                    output += f"• Skill '{skill}' loaded {loads}x but never useful — consider archiving\n"

            # Failure rate
            if failures > len(rows) * 0.3:
                output += f"• High failure rate ({failures}/{len(rows)}) — review agent prompts\n"

            if output == "💡 Improvement Suggestions\n\n":
                output += "No issues detected. System is performing well."

            return AgentResult(success=True, output=output)

        except Exception as e:
            return AgentResult(success=False, output=f"Error: {e}")
