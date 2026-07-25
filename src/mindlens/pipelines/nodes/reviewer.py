"""Reviewer node — quality checks the wiki page output."""

from __future__ import annotations

import json
import logging
from typing import Any

from mindlens.core.llm import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a quality reviewer for knowledge wiki pages.

Review the wiki page for:
1. Accuracy — does the summary match the source?
2. Completeness — are key claims captured?
3. Link quality — are wikilinks relevant?
4. Structure — is it well-organized?

Respond with JSON:
{
    "approved": true/false,
    "score": 0.0-1.0,
    "feedback": "specific improvement suggestions (empty if approved)",
    "issues": ["issue1", "issue2", ...]
}

Be strict. Only approve pages that are accurate and well-structured.
Score >= 0.8 = approved. Below 0.8 = needs revision.
"""

MAX_REVISIONS = 2


async def reviewer_node(state: dict[str, Any], llm: LLMClient) -> dict[str, Any]:
    """Review the generated wiki page for quality."""
    wiki_content = state.get("wiki_content", "")
    summary = state.get("raw_summary", "")
    revision_count = state.get("revision_count", 0)

    logger.info("Reviewer: checking quality (revision %d)", revision_count)

    if not wiki_content:
        state["needs_revision"] = False
        state["review_feedback"] = ""
        return state

    response = await llm.complete(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Source summary:\n{summary[:2000]}\n\n"
                f"Generated wiki page:\n{wiki_content[:3000]}"
            )},
        ],
        temperature=0.2,
    )

    # Strip markdown code fences if present
    cleaned = response.content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        review = json.loads(cleaned)
    except json.JSONDecodeError:
        # If LLM doesn't return JSON, approve by default
        review = {"approved": True, "score": 0.8, "feedback": "", "issues": []}

    approved = review.get("approved", True)
    score = review.get("score", 0.8)
    feedback = review.get("feedback", "")

    # Don't allow too many revisions
    if revision_count >= MAX_REVISIONS:
        logger.warning("Max revisions reached (%d), accepting current version", MAX_REVISIONS)
        state["needs_revision"] = False
        state["review_feedback"] = ""
        state["review_score"] = score
        return state

    if not approved and score < 0.8 and feedback:
        state["needs_revision"] = True
        state["review_feedback"] = feedback
        logger.info("Reviewer: revision needed — %s", feedback[:200])
    else:
        state["needs_revision"] = False
        state["review_feedback"] = ""

    state["review_score"] = score
    return state
