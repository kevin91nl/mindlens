"""SQLite database management for MindLens."""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

CORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    workspace TEXT,
    task_description TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    skills_loaded TEXT DEFAULT '[]',
    skills_useful TEXT DEFAULT '[]',
    duration_seconds REAL,
    success BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    source TEXT NOT NULL,
    data TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workspaces (
    name TEXT PRIMARY KEY,
    mission TEXT,
    constitution_path TEXT,
    repos_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

WORKSPACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'pending',
    result TEXT,
    agent_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS knowledge (
    id TEXT PRIMARY KEY,
    source_path TEXT,
    wiki_path TEXT,
    type TEXT,
    tags TEXT DEFAULT '[]',
    confidence REAL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS skills (
    name TEXT PRIMARY KEY,
    description TEXT,
    path TEXT,
    tokens INTEGER DEFAULT 0,
    useful_count INTEGER DEFAULT 0,
    last_used TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


async def init_core_db(db_path: Path) -> aiosqlite.Connection:
    """Initialize the core database with schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(db_path))
    await conn.executescript(CORE_SCHEMA)
    await conn.commit()
    logger.info("Core DB initialized at %s", db_path)
    return conn


async def init_workspace_db(db_path: Path) -> aiosqlite.Connection:
    """Initialize a workspace database with schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(db_path))
    await conn.executescript(WORKSPACE_SCHEMA)
    await conn.commit()
    logger.info("Workspace DB initialized at %s", db_path)
    return conn


async def record_agent_run(
    conn: aiosqlite.Connection,
    run_id: str,
    agent_name: str,
    workspace: str | None,
    task_description: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    skills_loaded: str,
    skills_useful: str,
    duration_seconds: float,
    success: bool,
) -> None:
    """Record an agent run in the core database."""
    await conn.execute(
        """INSERT INTO agent_runs
           (id, agent_name, workspace, task_description, input_tokens, output_tokens,
            cost_usd, skills_loaded, skills_useful, duration_seconds, success)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, agent_name, workspace, task_description,
         input_tokens, output_tokens, cost_usd,
         skills_loaded, skills_useful, duration_seconds, success),
    )
    await conn.commit()
