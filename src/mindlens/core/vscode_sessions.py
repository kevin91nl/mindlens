"""VS Code session reader — reads Copilot chat transcripts from disk."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

VSCODE_STORAGE = Path.home() / "Library" / "Application Support" / "Code" / "User" / "workspaceStorage"

# The main agent-sessions workspace where active chats live
AGENT_SESSIONS_WS = VSCODE_STORAGE / "-14f87f1a"


@dataclass
class ChatMessage:
    """A single message in a chat session."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: str
    turn_id: str | None = None
    tool_requests: list[dict] = field(default_factory=list)


@dataclass
class ChatSession:
    """A VS Code Copilot chat session."""
    session_id: str
    workspace: str
    workspace_name: str
    started: str
    messages: list[ChatMessage] = field(default_factory=list)
    event_count: int = 0
    transcript_path: str = ""

    @property
    def first_message(self) -> str:
        for m in self.messages:
            if m.role == "user":
                return m.content[:200]
        return "(no user message)"

    @property
    def last_message(self) -> str:
        for m in reversed(self.messages):
            if m.role == "assistant":
                return m.content[:200]
        return "(no assistant message)"

    @property
    def summary(self) -> str:
        return (
            f"Session {self.session_id[:8]}... | "
            f"{self.workspace_name} | "
            f"{self.started[:16]} | "
            f"{len(self.messages)} msgs | "
            f"{self.first_message[:80]}"
        )


class VSCodeSessionReader:
    """Reads VS Code Copilot chat transcripts from disk."""

    def __init__(self, storage_path: Path | None = None) -> None:
        self.storage_path = storage_path or VSCODE_STORAGE

    def discover_workspaces(self) -> list[dict[str, str]]:
        """Find all VS Code workspaces with chat transcripts."""
        workspaces = []
        if not self.storage_path.exists():
            return workspaces

        # Always include the main agent-sessions workspace first
        agent_ws = AGENT_SESSIONS_WS
        if agent_ws.exists():
            transcripts_dir = agent_ws / "GitHub.copilot-chat" / "transcripts"
            if transcripts_dir.exists():
                count = len(list(transcripts_dir.glob("*.jsonl")))
                if count > 0:
                    workspaces.append({
                        "id": agent_ws.name,
                        "folder": "agent-sessions",
                        "name": "agent-sessions (active)",
                        "sessions": count,
                        "transcripts_dir": str(transcripts_dir),
                    })

        for ws_dir in self.storage_path.iterdir():
            if not ws_dir.is_dir() or ws_dir == agent_ws:
                continue
            metadata = ws_dir / "workspace.json"
            transcripts_dir = ws_dir / "GitHub.copilot-chat" / "transcripts"

            if not metadata.exists() or not transcripts_dir.exists():
                continue

            try:
                with open(metadata) as f:
                    d = json.load(f)
                folder = d.get("folder", "")
                name = folder.split("/")[-1] if folder else ws_dir.name
                session_count = len(list(transcripts_dir.glob("*.jsonl")))
                if session_count > 0:
                    workspaces.append({
                        "id": ws_dir.name,
                        "folder": folder,
                        "name": name,
                        "sessions": session_count,
                        "transcripts_dir": str(transcripts_dir),
                    })
            except Exception:
                continue

        return sorted(workspaces, key=lambda w: w["sessions"], reverse=True)

    def list_sessions(self, workspace_filter: str | None = None, limit: int = 20) -> list[ChatSession]:
        """List chat sessions, optionally filtered by workspace name."""
        sessions = []
        workspaces = self.discover_workspaces()

        for ws in workspaces:
            if workspace_filter and workspace_filter.lower() not in ws["name"].lower():
                continue

            transcripts_dir = Path(ws["transcripts_dir"])
            files = sorted(transcripts_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)

            for f in files[:limit]:
                session = self._parse_session(f, ws)
                if session:
                    sessions.append(session)

        return sessions[:limit]

    def get_session(self, session_id_prefix: str) -> ChatSession | None:
        """Get a specific session by ID prefix."""
        workspaces = self.discover_workspaces()
        for ws in workspaces:
            transcripts_dir = Path(ws["transcripts_dir"])
            for f in transcripts_dir.glob("*.jsonl"):
                if f.stem.startswith(session_id_prefix):
                    return self._parse_session(f, ws)
        return None

    def search_sessions(self, query: str, limit: int = 10) -> list[ChatSession]:
        """Search across all sessions for a query string."""
        results = []
        workspaces = self.discover_workspaces()

        for ws in workspaces:
            transcripts_dir = Path(ws["transcripts_dir"])
            for f in transcripts_dir.glob("*.jsonl"):
                try:
                    content = f.read_text()
                    if query.lower() in content.lower():
                        session = self._parse_session(f, ws)
                        if session:
                            results.append(session)
                except Exception:
                    continue

        return results[:limit]

    def _parse_session(self, path: Path, ws: dict) -> ChatSession | None:
        """Parse a JSONL transcript into a ChatSession."""
        try:
            with open(path) as f:
                lines = [json.loads(l) for l in f if l.strip()]

            if not lines:
                return None

            session_id = lines[0].get("data", {}).get("sessionId", path.stem)
            started = lines[0].get("timestamp", "")

            messages = []
            for line in lines:
                msg_type = line.get("type", "")
                data = line.get("data", {})
                ts = line.get("timestamp", "")

                if msg_type == "user.message":
                    msg_text = data.get("content") or data.get("message") or data.get("text") or ""
                    messages.append(ChatMessage(
                        role="user",
                        content=msg_text,
                        timestamp=ts,
                        turn_id=data.get("turnId"),
                    ))
                elif msg_type == "assistant.message":
                    content = data.get("content", "")
                    reasoning = data.get("reasoningText", "")
                    if reasoning:
                        content = f"[Reasoning: {reasoning[:200]}...]\n{content}"
                    messages.append(ChatMessage(
                        role="assistant",
                        content=content,
                        timestamp=ts,
                        turn_id=data.get("turnId"),
                        tool_requests=data.get("toolRequests", []),
                    ))

            return ChatSession(
                session_id=session_id,
                workspace=ws["folder"],
                workspace_name=ws["name"],
                started=started,
                messages=messages,
                event_count=len(lines),
                transcript_path=str(path),
            )
        except Exception as e:
            logger.debug("Failed to parse %s: %s", path, e)
            return None
