"""Reader node — extracts text from raw input files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mindlens.core.llm import LLMClient

logger = logging.getLogger(__name__)


async def reader_node(state: dict[str, Any], llm: LLMClient) -> dict[str, Any]:
    """Read and extract content from a raw input file.

    Supports: .md, .txt, .pdf (text extraction), .url (fetch).
    """
    source_path = Path(state["source_path"])
    logger.info("Reader: processing %s", source_path.name)

    suffix = source_path.suffix.lower()

    if suffix in (".md", ".txt", ".text"):
        content = source_path.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".pdf":
        # Simple text extraction — try pdftotext if available
        try:
            import subprocess
            result = subprocess.run(
                ["pdftotext", str(source_path), "-"],
                capture_output=True, text=True, timeout=30,
            )
            content = result.stdout if result.returncode == 0 else f"[PDF: {source_path.name} — pdftotext not available]"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            content = f"[PDF: {source_path.name} — extraction not available]"
    elif suffix == ".url":
        # URL file — extract the URL and note it
        url = source_path.read_text().strip()
        content = f"[URL: {url}]\n\nContent to be fetched and processed."
    else:
        # Try reading as text
        try:
            content = source_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = f"[Binary file: {source_path.name}]"

    state["source_content"] = content
    state["source_filename"] = source_path.name
    return state
