"""Agent Registry — manages agent registration and creation."""

from __future__ import annotations

import logging
from typing import Any

from mindlens.agents.base import Agent

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Registry of available agents."""

    def __init__(self) -> None:
        self._agents: dict[str, type[Agent]] = {}

    def register(self, agent_cls: type[Agent]) -> None:
        """Register an agent class."""
        self._agents[agent_cls.name] = agent_cls
        logger.debug("Registered agent: %s", agent_cls.name)

    def get(self, name: str) -> type[Agent] | None:
        """Get an agent class by name."""
        return self._agents.get(name)

    def list_agents(self) -> list[dict[str, str]]:
        """List all registered agents."""
        return [
            {"name": cls.name, "description": cls.description}
            for cls in self._agents.values()
        ]

    def create(
        self,
        name: str,
        llm: Any,
        event_bus: Any,
        config: Any,
        scope: str = "global",
    ) -> Agent | None:
        """Create an agent instance by name with scope."""
        cls = self._agents.get(name)
        if cls:
            # Check if this is a YAML agent (has _yaml_path)
            yaml_path = getattr(cls, "_yaml_path", None)
            if yaml_path:
                from mindlens.agents.yaml_agent import YamlAgent
                agent = YamlAgent.from_yaml(yaml_path, llm=llm, event_bus=event_bus, config=config)
                agent.scope = scope
                return agent
            agent = cls(llm=llm, event_bus=event_bus, config=config)
            agent.scope = scope
            return agent
        return None
