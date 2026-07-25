"""Linker node — creates wikilinks and generates the wiki page."""

from __future__ import annotations

import logging
from typing import Any

from mindlens.core.llm import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a knowledge linker agent for an Obsidian vault.

Given a summary, key claims, entities, and tags, create a well-structured Obsidian wiki page.

Rules:
- Use [[wikilinks]] to connect to related pages (existing or to-be-created)
- Use YAML frontmatter with: source, created, type, tags, confidence
- Structure with headers: Key Points, My Notes, Sources
- Be concise but complete
- Flag uncertainty with [uncertain] tags

Respond with the COMPLETE markdown content of the wiki page (no JSON, just markdown).
"""


async def linker_node(state: dict[str, Any], llm: LLMClient) -> dict[str, Any]:
    """Generate wiki page with wikilinks from distilled content."""
    summary = state.get("raw_summary", "")
    claims = state.get("key_claims", [])
    entities = state.get("entities", [])
    tags = state.get("tags", [])
    filename = state.get("source_filename", "unknown")
    existing_wiki = state.get("existing_wiki", [])

    logger.info("Linker: generating wiki page for %s", filename)

    if not summary:
        state["wiki_content"] = ""
        state["wikilinks"] = []
        return state

    claims_text = "\n".join(f"- {c}" for c in claims) if claims else "- No claims extracted"
    entities_text = ", ".join(entities) if entities else "none"
    existing_text = ", ".join(existing_wiki[:20]) if existing_wiki else "none (new vault)"

    user_message = (
        f"Source file: {filename}\n\n"
        f"Summary:\n{summary}\n\n"
        f"Key claims:\n{claims_text}\n\n"
        f"Entities: {entities_text}\n\n"
        f"Tags: {', '.join(tags)}\n\n"
        f"Existing wiki pages: {existing_text}\n\n"
        f"Generate the complete wiki page markdown."
    )

    response = await llm.complete(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.5,
    )

    wiki_content = response.content

    # Extract wikilinks from the content
    import re
    wikilinks = re.findall(r'\[\[([^\]|]+)', wiki_content)

    state["wiki_content"] = wiki_content
    state["wikilinks"] = list(set(wikilinks))

    return state
