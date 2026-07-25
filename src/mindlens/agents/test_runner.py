"""Test Runner — verifies improvements actually work."""

from __future__ import annotations

import logging

from mindlens.agents.base import Agent, AgentContext, AgentResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Je bent de Test Runner van MindLens Cortex.

Je verifieert of verbeteringen daadwerkelijk werken door:
1. De huidige staat te meten
2. De voorgestelde verandering te evalueren
3. Te controleren of het verwachte resultaat wordt bereikt

Geef een gestructureerd testrapport in het Nederlands:
- ✅ geslaagd / ❌ gefaald
- Wat werd getest
- Wat het resultaat was
- Aanbevelingen
"""


class TestRunner(Agent):
    name = "test_runner"
    description = "Verificatie van verbeteringen, regressietests"
    scope = "global"

    async def run(self, context: AgentContext) -> AgentResult:
        """Run tests on a proposed improvement."""
        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Test deze verbetering:\n\n{context.task}",
            temperature=0.2,
        )

        return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)
