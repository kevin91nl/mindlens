"""VS Code Session Agent — list, view, search VS Code Copilot chats from Telegram."""

from __future__ import annotations

import json
import logging
import subprocess

from mindlens.agents.base import Agent, AgentContext, AgentResult
from mindlens.core.vscode_sessions import VSCodeSessionReader

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a VS Code session manager for MindLens.

You can:
- List chat sessions across workspaces
- View session details and messages
- Search across all sessions
- Start new VS Code chats

When the user asks about VS Code sessions, respond with a JSON object:
{
    "action": "list" | "view" | "search" | "start" | "workspaces",
    "workspace": "workspace name filter (optional)",
    "session_id": "session ID prefix (optional)",
    "query": "search query (optional)",
    "prompt": "new chat prompt (optional)"
}
"""


class VSCodeSessionAgent(Agent):
    name = "vscode_session_agent"
    description = "List, view, search VS Code Copilot chat sessions"
    capabilities = ["list_sessions", "view_session", "search_sessions", "start_chat"]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.reader = VSCodeSessionReader()

    async def run(self, context: AgentContext) -> AgentResult:
        task = context.task.lower()

        # Direct commands (no LLM needed)
        if "workspaces" in task or "list workspaces" in task:
            return self._list_workspaces()

        if ("list" in task or "show" in task or "alle" in task or "welke" in task) and ("session" in task or "chat" in task or "sessie" in task):
            ws_filter = None
            for word in ["riskstudio", "phd", "tuvia", "abibia", "mindlens"]:
                if word in task:
                    ws_filter = word
                    break
            return self._list_sessions(ws_filter)

        if "search" in task or "zoek" in task:
            query = task.replace("search", "").replace("for", "").replace("zoek", "").strip()
            if query:
                return self._search_sessions(query)

        if "view" in task or "show session" in task or "bekijk" in task:
            # Try to extract session ID
            import re
            match = re.search(r'[0-9a-f]{8}', task)
            if match:
                return self._view_session(match.group())

        # Default: list all recent sessions
        return self._list_sessions()

    def _list_workspaces(self) -> AgentResult:
        workspaces = self.reader.discover_workspaces()
        if not workspaces:
            return AgentResult(success=True, output="No VS Code workspaces with chat sessions found.")

        output = "📂 VS Code Workspaces with Chat Sessions:\n\n"
        total = 0
        for ws in workspaces:
            output += f"• **{ws['name']}** — {ws['sessions']} sessions\n"
            total += ws['sessions']
        output += f"\nTotal: {total} sessions across {len(workspaces)} workspaces"
        return AgentResult(success=True, output=output)

    def _list_sessions(self, workspace_filter: str | None = None) -> AgentResult:
        sessions = self.reader.list_sessions(workspace_filter, limit=15)
        if not sessions:
            return AgentResult(success=True, output=f"No sessions found{f' for {workspace_filter}' if workspace_filter else ''}.")

        output = f"💬 VS Code Chat Sessions"
        if workspace_filter:
            output += f" ({workspace_filter})"
        output += ":\n\n"
        for s in sessions:
            output += f"• `{s.session_id[:8]}` | {s.workspace_name} | {s.started[:16]} | {len(s.messages)} msgs\n  _{s.first_message[:80]}_\n\n"
        return AgentResult(success=True, output=output)

    def _view_session(self, session_id: str) -> AgentResult:
        session = self.reader.get_session(session_id)
        if not session:
            return AgentResult(success=True, output=f"Session '{session_id}' not found.")

        output = f"📝 Session {session.session_id[:8]}...\n"
        output += f"Workspace: {session.workspace_name}\n"
        output += f"Started: {session.started[:19]}\n"
        output += f"Events: {session.event_count}\n\n"

        for msg in session.messages[-10:]:  # Last 10 messages
            role = "👤" if msg.role == "user" else "🤖"
            content = msg.content[:300].replace("\n", " ")
            output += f"{role} {content}\n\n"

        return AgentResult(success=True, output=output)

    def _search_sessions(self, query: str) -> AgentResult:
        sessions = self.reader.search_sessions(query, limit=10)
        if not sessions:
            return AgentResult(success=True, output=f"No sessions found matching '{query}'.")

        output = f"🔍 Search results for '{query}':\n\n"
        for s in sessions:
            output += f"• `{s.session_id[:8]}` | {s.workspace_name} | {s.started[:16]}\n  _{s.first_message[:80]}_\n\n"
        return AgentResult(success=True, output=output)

    def _start_chat(self, prompt: str) -> AgentResult:
        try:
            subprocess.Popen(
                ["code", "chat", prompt, "--mode", "agent"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return AgentResult(success=True, output=f"✅ VS Code chat started with: _{prompt[:100]}_")
        except Exception as e:
            return AgentResult(success=False, output=f"Failed to start VS Code chat: {e}")
