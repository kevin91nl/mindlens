"""Session Observer — reads VS Code chat transcripts, identifies waste patterns."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta

from mindlens.agents.base import Agent, AgentContext, AgentResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Session Observer of MindLens Cortex.

You analyze VS Code Copilot chat sessions to identify waste patterns.

Look for:
1. Repeated errors (same error multiple times)
2. Slow responses (long wait time between messages)
3. Failed routing (wrong agent chosen)
4. Wasted tokens (unnecessarily long responses, repetition)
5. Patterns of inefficiency

Always respond in the same language as the user's message with a structured report.
"""


class SessionObserver(Agent):
    name = "session_observer"
    description = "Reads VS Code sessions, identifies waste and error patterns"
    scope = "global"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sessions_dir = self.config.copilot_transcripts_path

    async def run(self, context: AgentContext) -> AgentResult:
        task = context.task.lower()

        if "recent" in task or "latest" in task:
            return await self._analyze_recent_sessions()
        elif "waste" in task:
            return await self._analyze_waste()
        elif "error" in task:
            return await self._analyze_errors()
        else:
            return await self._analyze_recent_sessions()

    async def _analyze_recent_sessions(self) -> AgentResult:
        """Analyze recent sessions for patterns."""
        if not self._sessions_dir or not self._sessions_dir.exists():
            return AgentResult(success=True, output="No sessions found.")

        files = sorted(self._sessions_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)

        analysis = []
        for f in files[:5]:
            try:
                lines = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
                mtime = datetime.fromtimestamp(f.stat().st_mtime)

                user_msgs = [l for l in lines if l.get("type") == "user.message"]
                asst_msgs = [l for l in lines if l.get("type") == "assistant.message"]

                # Count errors
                errors = [l for l in lines if "error" in str(l).lower() and l.get("type") != "user.message"]

                analysis.append({
                    "session": f.stem[:8],
                    "date": mtime.strftime("%Y-%m-%d %H:%M"),
                    "events": len(lines),
                    "user_msgs": len(user_msgs),
                    "asst_msgs": len(asst_msgs),
                    "errors": len(errors),
                    "last_user": next((l.get("data", {}).get("content", "")[:80] for l in reversed(user_msgs) if l.get("data", {}).get("content")), ""),
                })
            except Exception:
                continue

        if not analysis:
            return AgentResult(success=True, output="No analyzable sessions found.")

        # Use LLM to analyze patterns
        analysis_text = json.dumps(analysis, indent=2)
        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Analyze these recent VS Code sessions and identify patterns:\n\n{analysis_text}",
            temperature=0.3,
        )

        return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)

    async def _analyze_waste(self) -> AgentResult:
        """Identify wasted tokens and time."""
        if not self._sessions_dir or not self._sessions_dir.exists():
            return AgentResult(success=True, output="No sessions found.")

        files = sorted(self._sessions_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)

        waste_signals = []
        for f in files[:10]:
            try:
                lines = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]

                # Detect waste patterns
                user_msgs = [l for l in lines if l.get("type") == "user.message"]
                asst_msgs = [l for l in lines if l.get("type") == "assistant.message"]

                # Count tool calls that failed
                tool_calls = [l for l in lines if "tool" in l.get("type", "").lower()]
                failed_tools = [l for l in tool_calls if "error" in str(l).lower()]

                # Very long sessions with few user messages
                if len(lines) > 100 and len(user_msgs) < 5:
                    waste_signals.append(f"Session {f.stem[:8]}: {len(lines)} events, but only {len(user_msgs)} user messages")

                # Many errors
                if len(failed_tools) > 3:
                    waste_signals.append(f"Session {f.stem[:8]}: {len(failed_tools)} failed tool calls")

            except Exception:
                continue

        if not waste_signals:
            return AgentResult(success=True, output="No significant waste detected in recent sessions.")

        waste_text = "\n".join(waste_signals)
        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Analyze these waste signals and provide concrete improvement suggestions:\n\n{waste_text}",
            temperature=0.3,
        )

        return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)

    async def _analyze_errors(self) -> AgentResult:
        """Analyze error patterns across sessions."""
        if not self._sessions_dir or not self._sessions_dir.exists():
            return AgentResult(success=True, output="No sessions found.")

        files = sorted(self._sessions_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)

        error_patterns = {}
        for f in files[:10]:
            try:
                content = f.read_text()
                # Find error-like strings
                import re
                errors = re.findall(r'"error[^"]*"[^}]*"message[^"]*"([^"]{10,100})"', content)
                for err in errors:
                    key = err[:50]
                    error_patterns[key] = error_patterns.get(key, 0) + 1
            except Exception:
                continue

        if not error_patterns:
            return AgentResult(success=True, output="No error patterns found in recent sessions.")

        # Sort by frequency
        sorted_errors = sorted(error_patterns.items(), key=lambda x: -x[1])
        error_text = "\n".join(f"  {count}x: {err}" for err, count in sorted_errors[:10])

        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Analyze these repeated error patterns and provide solutions:\n\n{error_text}",
            temperature=0.3,
        )

        return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)
