"""Efficiency Analyst — tracks token/cost trends, identifies waste."""

from __future__ import annotations

import json
import logging

import aiosqlite

from mindlens.agents.base import Agent, AgentContext, AgentResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Je bent de Efficiency Analyst van MindLens Cortex.

Je analyseert token- en kostendata om verspilling te identificeren en verbeteringen voor te stellen.

Geef een gestructureerd rapport in het Nederlands met:
1. Huidige status (tokens, kosten, trends)
2. Top verspillingen
3. Concrete verbetervoorstellen met verwachte impact
"""


class EfficiencyAnalyst(Agent):
    name = "efficiency_analyst"
    description = "Token/cost tracking, trendanalyse, verspilling identificatie"
    scope = "global"

    async def run(self, context: AgentContext) -> AgentResult:
        task = context.task.lower()

        if "dagelijks" in task or "daily" in task or "rapport" in task:
            return await self._daily_report()
        elif "trend" in task:
            return await self._trend_analysis()
        elif "waste" in task or "verspil" in task:
            return await self._waste_analysis()
        else:
            return await self._daily_report()

    async def _daily_report(self) -> AgentResult:
        """Generate daily efficiency report."""
        try:
            conn = await aiosqlite.connect(str(self.config.core_db_path()))

            # Today's stats
            cursor = await conn.execute("""
                SELECT agent_name, workspace,
                       COUNT(*) as runs,
                       SUM(input_tokens) as total_in,
                       SUM(output_tokens) as total_out,
                       SUM(cost_usd) as total_cost,
                       AVG(duration_seconds) as avg_duration,
                       SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes
                FROM agent_runs
                WHERE DATE(created_at) = DATE('now')
                GROUP BY agent_name, workspace
                ORDER BY total_cost DESC
            """)
            rows = await cursor.fetchall()

            # 7-day trend
            cursor = await conn.execute("""
                SELECT DATE(created_at) as day,
                       SUM(input_tokens + output_tokens) as tokens,
                       SUM(cost_usd) as cost,
                       COUNT(*) as runs
                FROM agent_runs
                WHERE created_at >= DATE('now', '-7 days')
                GROUP BY day
                ORDER BY day
            """)
            trend = await cursor.fetchall()
            await conn.close()

            if not rows:
                return AgentResult(success=True, output="📊 Geen agent runs vandaag.")

            # Build report
            report = "📊 Dagelijks Efficiency Rapport\n\n"
            report += "**Vandaag:**\n"
            total_tokens = 0
            total_cost = 0
            for agent, ws, runs, in_tok, out_tok, cost, duration, success in rows:
                rate = (success / runs * 100) if runs else 0
                total_tokens += (in_tok or 0) + (out_tok or 0)
                total_cost += cost or 0
                report += f"• {agent} [{ws}]: {runs} runs, {rate:.0f}% success, {in_tok+out_tok} tokens, ${cost:.4f}\n"

            report += f"\n**Totaal:** {total_tokens} tokens, ${total_cost:.4f}\n"

            if trend:
                report += "\n**7-daagse trend:**\n"
                for day, tokens, cost, runs in trend:
                    report += f"  {day}: {tokens} tokens, ${cost:.4f}, {runs} runs\n"

            # Use LLM for analysis
            content, in_tok, out_tok = await self._llm_complete(
                SYSTEM_PROMPT,
                f"Genereer een efficiency rapport op basis van deze data:\n\n{report}",
                temperature=0.3,
            )

            return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)

        except Exception as e:
            return AgentResult(success=False, output=f"Fout bij ophalen data: {e}")

    async def _trend_analysis(self) -> AgentResult:
        """Analyze token/cost trends over time."""
        try:
            conn = await aiosqlite.connect(str(self.config.core_db_path()))
            cursor = await conn.execute("""
                SELECT DATE(created_at) as day,
                       SUM(input_tokens) as in_tok,
                       SUM(output_tokens) as out_tok,
                       SUM(cost_usd) as cost,
                       COUNT(*) as runs,
                       AVG(duration_seconds) as avg_duration
                FROM agent_runs
                WHERE created_at >= DATE('now', '-14 days')
                GROUP BY day
                ORDER BY day
            """)
            rows = await cursor.fetchall()
            await conn.close()

            if not rows:
                return AgentResult(success=True, output="Geen data voor trendanalyse.")

            data = []
            for day, in_tok, out_tok, cost, runs, duration in rows:
                data.append({
                    "day": day,
                    "tokens": (in_tok or 0) + (out_tok or 0),
                    "cost": cost or 0,
                    "runs": runs,
                    "avg_duration": round(duration or 0, 1),
                })

            content, in_tok, out_tok = await self._llm_complete(
                SYSTEM_PROMPT,
                f"Analyseer deze 14-daagse trends en identificeer verbeteringen:\n\n{json.dumps(data, indent=2)}",
                temperature=0.3,
            )

            return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)

        except Exception as e:
            return AgentResult(success=False, output=f"Fout: {e}")

    async def _waste_analysis(self) -> AgentResult:
        """Identify specific waste patterns."""
        try:
            conn = await aiosqlite.connect(str(self.config.core_db_path()))
            cursor = await conn.execute("""
                SELECT agent_name, workspace, task_description,
                       input_tokens, output_tokens, cost_usd, duration_seconds, success
                FROM agent_runs
                WHERE created_at >= DATE('now', '-7 days')
                ORDER BY cost_usd DESC
                LIMIT 20
            """)
            rows = await cursor.fetchall()
            await conn.close()

            if not rows:
                return AgentResult(success=True, output="Geen data voor waste analyse.")

            expensive = []
            for agent, ws, task, in_tok, out_tok, cost, duration, success in rows:
                expensive.append({
                    "agent": agent,
                    "workspace": ws,
                    "task": (task or "")[:80],
                    "tokens": (in_tok or 0) + (out_tok or 0),
                    "cost": cost or 0,
                    "duration": round(duration or 0, 1),
                    "success": bool(success),
                })

            content, in_tok, out_tok = await self._llm_complete(
                SYSTEM_PROMPT,
                f"Identificeer verspilling in deze duurste agent runs:\n\n{json.dumps(expensive, indent=2)}",
                temperature=0.3,
            )

            return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)

        except Exception as e:
            return AgentResult(success=False, output=f"Fout: {e}")
