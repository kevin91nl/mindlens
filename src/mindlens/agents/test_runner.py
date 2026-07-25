"""Test Runner — verifies improvements actually work."""

from __future__ import annotations

import logging

from mindlens.agents.base import Agent, AgentContext, AgentResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Test Runner of MindLens Cortex.

You verify whether improvements actually work by:
1. Measuring the current state
2. Evaluating the proposed change
3. Checking whether the expected result is achieved

Always respond in the same language as the user's message with a structured test report:
- ✅ passed / ❌ failed
- What was tested
- What the result was
- Recommendations
"""


class TestRunner(Agent):
    name = "test_runner"
    description = "Verification of improvements, regression tests"
    scope = "global"

    async def run(self, context: AgentContext) -> AgentResult:
        """Run tests on a proposed improvement."""
        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Test deze verbetering:\n\n{context.task}",
            temperature=0.2,
        )

        return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)
