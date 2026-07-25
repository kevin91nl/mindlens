"""Event Bus — pub/sub for inter-agent communication."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """An event published on the bus."""

    topic: str
    source: str  # agent or workspace name
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:
        return f"[{self.source}] {self.topic}: {self.data}"


# Type alias for event handlers
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """In-process pub/sub event bus.

    Agents publish events, other agents subscribe to topics.
    Supports wildcard subscriptions with '*'.
    All events are logged for the Chief of Staff briefing.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._history: list[Event] = []
        self._max_history = 1000

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        """Subscribe to a topic. Use '*' for all events."""
        self._handlers[topic].append(handler)
        logger.debug("Subscribed to %s: %s", topic, handler.__qualname__)

    def unsubscribe(self, topic: str, handler: EventHandler) -> None:
        """Unsubscribe a handler from a topic."""
        if topic in self._handlers:
            self._handlers[topic] = [h for h in self._handlers[topic] if h != handler]

    async def publish(self, event: Event) -> None:
        """Publish an event to all matching subscribers."""
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        logger.info("Event: %s", event)

        # Collect matching handlers
        handlers: list[EventHandler] = []
        for topic, topic_handlers in self._handlers.items():
            if topic == "*" or topic == event.topic:
                handlers.extend(topic_handlers)

        # Run all handlers concurrently
        if handlers:
            await asyncio.gather(
                *[self._safe_call(h, event) for h in handlers],
                return_exceptions=True,
            )

    async def _safe_call(self, handler: EventHandler, event: Event) -> None:
        """Call a handler, catching and logging exceptions."""
        try:
            await handler(event)
        except Exception:
            logger.exception("Handler %s failed for event %s", handler.__qualname__, event.topic)

    def history(self, topic: str | None = None, limit: int = 50) -> list[Event]:
        """Get recent event history, optionally filtered by topic."""
        events = self._history
        if topic:
            events = [e for e in events if e.topic == topic]
        return events[-limit:]
