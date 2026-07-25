"""Agent Architect — designs new agents, generates prompts."""

from __future__ import annotations

import json
import logging

import yaml

from mindlens.agents.base import Agent, AgentContext, AgentResult
from mindlens.core.event_bus import Event

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Agent Architect for MindLens. You design new agents.

When asked to create an agent, respond with a JSON object:
{
    "name": "agent_name",
    "description": "what this agent does",
    "type": "knowledge" | "coder" | "manager",
    "capabilities": ["list", "of", "capabilities"],
    "system_prompt": "the agent's system prompt",
    "skills": ["relevant", "skill", "names"]
}

Make agents focused and single-purpose. One agent = one job.
"""


class AgentArchitect(Agent):
    name = "agent_architect"
    description = "Designs new agents, generates prompts, creates agent configs"
    capabilities = ["design_agent", "generate_prompt", "create_agent_config"]

    async def run(self, context: AgentContext) -> AgentResult:
        """Design and create a new agent."""
        workspace = context.workspace

        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Workspace: {workspace}\nRequest: {context.task}",
            temperature=0.5,
        )

        try:
            agent_design = json.loads(self._strip_code_fences(content))
        except json.JSONDecodeError:
            return AgentResult(
                success=False,
                output=f"Could not parse agent design: {content}",
                input_tokens=in_tok,
                output_tokens=out_tok,
            )

        # Save agent config if workspace specified
        if workspace:
            agents_dir = self.config.workspace_path(workspace) / ".mindlens" / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)

            agent_file = agents_dir / f"{agent_design['name']}.yaml"
            agent_config = {
                "name": agent_design["name"],
                "description": agent_design["description"],
                "type": agent_design.get("type", "knowledge"),
                "capabilities": agent_design.get("capabilities", []),
                "system_prompt": agent_design.get("system_prompt", ""),
                "skills": agent_design.get("skills", []),
            }
            agent_file.write_text(yaml.dump(agent_config, default_flow_style=False))

            await self.event_bus.publish(Event(
                topic="agent.created",
                source="agent_architect",
                data={"agent": agent_design["name"], "workspace": workspace},
            ))

            return AgentResult(
                success=True,
                output=(
                    f"✅ Agent '{agent_design['name']}' designed.\n"
                    f"  Description: {agent_design['description']}\n"
                    f"  Type: {agent_design.get('type', 'knowledge')}\n"
                    f"  Config saved: {agent_file}\n\n"
                    f"System prompt:\n{agent_design.get('system_prompt', '(none)')[:500]}"
                ),
                input_tokens=in_tok,
                output_tokens=out_tok,
            )

        return AgentResult(
            success=True,
            output=f"Agent design:\n{json.dumps(agent_design, indent=2)}",
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
