"""LangGraph pipeline — raw→wiki knowledge distillation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph
from typing import TypedDict

from mindlens.core.llm import LLMClient
from mindlens.pipelines.nodes.reader import reader_node
from mindlens.pipelines.nodes.distiller import distiller_node
from mindlens.pipelines.nodes.linker import linker_node
from mindlens.pipelines.nodes.reviewer import reviewer_node

logger = logging.getLogger(__name__)


class PipelineState(TypedDict, total=False):
    """State for the raw→wiki pipeline."""
    source_path: str
    source_content: str
    source_filename: str
    workspace_path: str
    raw_summary: str
    key_claims: list[str]
    entities: list[str]
    tags: list[str]
    wiki_content: str
    wikilinks: list[str]
    existing_wiki: list[str]
    needs_revision: bool
    revision_count: int
    review_feedback: str
    review_score: float


def build_raw_to_wiki_pipeline(llm: LLMClient) -> Any:
    """Build the raw→wiki LangGraph pipeline.

    Flow:
        raw_file → Reader → Distiller → Linker → Reviewer → output
                                    ↑                     │
                                    └── (revise if fails) ┘
    """
    graph = StateGraph(PipelineState)

    # Add nodes — wrap async functions properly
    async def reader(state):
        return await reader_node(state, llm)

    async def distiller(state):
        return await distiller_node(state, llm)

    async def linker(state):
        return await linker_node(state, llm)

    async def reviewer(state):
        return await reviewer_node(state, llm)

    graph.add_node("reader", reader)
    graph.add_node("distiller", distiller)
    graph.add_node("linker", linker)
    graph.add_node("reviewer", reviewer)

    # Define edges — linear flow (revision loop can be added later)
    graph.set_entry_point("reader")
    graph.add_edge("reader", "distiller")
    graph.add_edge("distiller", "linker")
    graph.add_edge("linker", "reviewer")
    graph.add_edge("reviewer", END)

    return graph.compile()


async def run_pipeline(
    llm: LLMClient,
    source_path: Path,
    workspace_path: Path,
    existing_wiki: list[str] | None = None,
) -> dict[str, Any]:
    """Run the raw→wiki pipeline on a source file."""
    pipeline = build_raw_to_wiki_pipeline(llm)

    initial_state: PipelineState = PipelineState(
        source_path=str(source_path),
        source_content="",
        workspace_path=str(workspace_path),
        raw_summary="",
        key_claims=[],
        entities=[],
        tags=[],
        wiki_content="",
        wikilinks=[],
        existing_wiki=existing_wiki or [],
        needs_revision=False,
        revision_count=0,
        review_feedback="",
    )

    # Run pipeline
    final_state = await pipeline.ainvoke(initial_state)

    return dict(final_state)
