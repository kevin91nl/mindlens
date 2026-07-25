"""Distiller node — summarizes and extracts key information."""

from __future__ import annotations

import json
import logging
from typing import Any

from mindlens.core.llm import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a knowledge distillation agent.

Given raw text content, extract:
1. A concise summary (2-3 paragraphs)
2. Key claims or findings (bullet points)
3. Important entities (people, organizations, concepts, tools)
4. Relevant tags for categorization

Respond with JSON:
{
    "summary": "concise summary text",
    "key_claims": ["claim 1", "claim 2", ...],
    "entities": ["entity1", "entity2", ...],
    "tags": ["tag1", "tag2", ...]
}

Be precise. Extract only what's actually in the text. Flag uncertainty.
"""


async def distiller_node(state: dict[str, Any], llm: LLMClient) -> dict[str, Any]:
    """Distill raw content into structured information."""
    content = state.get("source_content", "")
    filename = state.get("source_filename", "unknown")

    logger.info("Distiller: extracting from %s", filename)

    if not content or content.startswith("["):
        # Skip if no real content
        state["raw_summary"] = content or "No content available."
        state["key_claims"] = []
        state["entities"] = []
        state["tags"] = []
        return state

    # Truncate if too long (keep under ~12k chars for context window)
    if len(content) > 12000:
        content = content[:12000] + "\n\n[...truncated...]"

    revision_feedback = state.get("review_feedback", "")
    user_message = f"Source: {filename}\n\nContent:\n{content}"
    if revision_feedback:
        user_message += f"\n\nRevision feedback from reviewer:\n{revision_feedback}\n\nPlease improve based on this feedback."

    response = await llm.complete(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.3,
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
        extracted = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: use raw response as summary
        extracted = {
            "summary": response.content[:2000],
            "key_claims": [],
            "entities": [],
            "tags": [],
        }

    state["raw_summary"] = extracted.get("summary", "")
    state["key_claims"] = extracted.get("key_claims", [])
    state["entities"] = extracted.get("entities", [])
    state["tags"] = extracted.get("tags", [])
    state["revision_count"] = state.get("revision_count", 0) + (1 if revision_feedback else 0)
    state["review_feedback"] = ""

    return state
