"""File watcher — triggers pipeline when new files appear in raw/ directories."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent
from watchdog.observers import Observer

if TYPE_CHECKING:
    from mindlens.core.event_bus import EventBus

logger = logging.getLogger(__name__)

# Debounce: ignore events for the same file within this many seconds
_DEBOUNCE_SECONDS = 5.0


class RawFileHandler(FileSystemEventHandler):
    """Handles new/modified files in raw/ directories by publishing events."""

    def __init__(self, event_bus: EventBus, workspace_name: str) -> None:
        self.event_bus = event_bus
        self.workspace_name = workspace_name
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_event: dict[str, float] = {}  # file_path → timestamp

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the event loop for async event publishing."""
        self._loop = loop

    def _should_handle(self, path: Path) -> bool:
        """Check if a file should trigger an event (with debouncing)."""
        if path.name.startswith(".") or path.name.endswith(".tmp"):
            return False
        if path.name == "index.yaml":
            return False
        # Debounce: skip if same file triggered recently
        key = str(path)
        now = time.monotonic()
        last = self._last_event.get(key, 0)
        if now - last < _DEBOUNCE_SECONDS:
            logger.debug("Debounced: %s (%.1fs since last)", path.name, now - last)
            return False
        self._last_event[key] = now
        return True

    def on_created(self, event: FileCreatedEvent) -> None:
        """Handle new file creation."""
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not self._should_handle(path):
            return
        logger.info("New raw file: %s in %s", path.name, self.workspace_name)
        self._schedule_event(path, "raw_file.created")

    def on_modified(self, event: FileModifiedEvent) -> None:
        """Handle file modification."""
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not self._should_handle(path):
            return
        logger.info("Modified raw file: %s in %s", path.name, self.workspace_name)
        self._schedule_event(path, "raw_file.modified")

    def _schedule_event(self, path: Path, topic: str) -> None:
        """Schedule an event publication on the event loop."""
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._publish_event(path, topic),
                self._loop,
            )

    async def _publish_event(self, path: Path, topic: str) -> None:
        """Publish a file event."""
        from mindlens.core.event_bus import Event

        await self.event_bus.publish(Event(
            topic=topic,
            source=f"file_watcher:{self.workspace_name}",
            data={
                "workspace": self.workspace_name,
                "file_path": str(path),
                "file_name": path.name,
                "file_suffix": path.suffix,
            },
        ))


class FileWatcher:
    """Watches raw/ directories across all workspaces for new files."""

    def __init__(self, event_bus: EventBus, vault_path: Path) -> None:
        self.event_bus = event_bus
        self.vault_path = vault_path
        self._observer = Observer()
        self._handlers: list[RawFileHandler] = []

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Start watching all workspace raw/ directories.

        Args:
            loop: The running event loop. Must be provided from async context.
        """
        if loop is None:
            loop = asyncio.get_running_loop()

        for item in self.vault_path.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                raw_dir = item / "raw"
                if raw_dir.exists():
                    handler = RawFileHandler(self.event_bus, item.name)
                    handler.set_loop(loop)
                    self._observer.schedule(handler, str(raw_dir), recursive=False)
                    self._handlers.append(handler)
                    logger.info("Watching: %s", raw_dir)

        self._observer.start()
        logger.info("File watcher started for %d workspaces", len(self._handlers))

    def stop(self) -> None:
        """Stop watching."""
        self._observer.stop()
        self._observer.join()
        logger.info("File watcher stopped")
