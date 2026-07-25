"""Hot-reload YAML agent definitions.

Watches all agents/*.yaml files in the vault. When a file changes,
the agent registry and scheduler are updated immediately.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

import yaml
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileDeletedEvent
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class AgentDefinition:
    """Parsed YAML agent definition."""

    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self.path = path
        self.name = data.get("name", path.stem)
        self.description = data.get("description", "")
        self.type = data.get("type", "unknown")
        self.scope = data.get("scope", "global")
        self.backend = data.get("backend", "llm")
        self.schedule = data.get("schedule")
        self.notify = data.get("notify", "summary")
        self.events = data.get("events", [])
        self.capabilities = data.get("capabilities", [])
        self.tools = data.get("tools", [])
        self.skills = data.get("skills", [])
        self.system_prompt = data.get("system_prompt", "")
        self.raw_data = data

    def __repr__(self) -> str:
        return f"AgentDef({self.name}, type={self.type}, scope={self.scope})"


class AgentHotReloader:
    """Watches vault for YAML agent changes and triggers reloads."""

    def __init__(
        self,
        vault_path: Path,
        on_agent_added: Callable[[AgentDefinition], None],
        on_agent_changed: Callable[[AgentDefinition], None],
        on_agent_removed: Callable[[str], None],
    ) -> None:
        self.vault_path = vault_path
        self.on_agent_added = on_agent_added
        self.on_agent_changed = on_agent_changed
        self.on_agent_removed = on_agent_removed
        self._observer = Observer()
        self._known_agents: dict[str, AgentDefinition] = {}  # name → definition
        self._last_reload: float = 0
        self._reload_debounce: float = 2.0  # seconds

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Start watching all agents/ directories in the vault."""
        self._loop = loop
        self._scan_all()

        # Watch all agents/ directories
        for agents_dir in self._find_agents_dirs():
            handler = _AgentFileHandler(self)
            self._observer.schedule(handler, str(agents_dir), recursive=False)
            logger.info("Hot-reload watching: %s", agents_dir)

        self._observer.start()
        logger.info("Agent hot-reloader started. Monitoring %d directories.", len(self._find_agents_dirs()))

    def stop(self) -> None:
        """Stop watching."""
        self._observer.stop()
        self._observer.join()
        logger.info("Agent hot-reloader stopped")

    def _find_agents_dirs(self) -> list[Path]:
        """Find all agents/ directories in the vault."""
        dirs = []

        # Global agents
        global_dir = self.vault_path / "agents"
        if global_dir.exists():
            dirs.append(global_dir)

        # Workspace agents
        for item in self.vault_path.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                ws_agents = item / "agents"
                if ws_agents.exists():
                    dirs.append(ws_agents)

        return dirs

    def _scan_all(self) -> None:
        """Scan all agents/ directories and build initial state."""
        for agents_dir in self._find_agents_dirs():
            for yaml_file in agents_dir.glob("*.yaml"):
                if yaml_file.name == "INDEX.md":
                    continue
                defn = self._parse_yaml(yaml_file)
                if defn:
                    self._known_agents[defn.name] = defn
                    logger.info("Loaded agent definition: %s", defn.name)

    def _parse_yaml(self, path: Path) -> AgentDefinition | None:
        """Parse a YAML agent definition file."""
        try:
            data = yaml.safe_load(path.read_text()) or {}
            if not data.get("name"):
                return None
            return AgentDefinition(path=path, data=data)
        except Exception as e:
            logger.warning("Failed to parse agent YAML %s: %s", path, e)
            return None

    def handle_file_change(self, path: Path) -> None:
        """Handle a file change in an agents/ directory."""
        if not path.suffix == ".yaml":
            return

        # Debounce
        now = time.monotonic()
        if now - self._last_reload < self._reload_debounce:
            return
        self._last_reload = now

        # Schedule reload on event loop
        if hasattr(self, '_loop') and self._loop and not self._loop.is_closed():
            import asyncio
            asyncio.run_coroutine_threadsafe(
                self._reload_agent(path),
                self._loop,
            )

    async def _reload_agent(self, path: Path) -> None:
        """Reload a single agent definition."""
        defn = self._parse_yaml(path)
        old_defn = self._known_agents.get(path.stem)

        if defn:
            if old_defn:
                # Changed
                self._known_agents[defn.name] = defn
                logger.info("Agent definition changed: %s", defn.name)
                self.on_agent_changed(defn)
            else:
                # New
                self._known_agents[defn.name] = defn
                logger.info("New agent definition: %s", defn.name)
                self.on_agent_added(defn)
        else:
            # Deleted or invalid
            if old_defn:
                del self._known_agents[old_defn.name]
                logger.info("Agent definition removed: %s", old_defn.name)
                self.on_agent_removed(old_defn.name)

    def handle_file_deletion(self, path: Path) -> None:
        """Handle a file deletion in an agents/ directory."""
        if not path.suffix == ".yaml":
            return

        name = path.stem
        if name in self._known_agents:
            del self._known_agents[name]
            logger.info("Agent definition removed: %s", name)
            if hasattr(self, '_loop') and self._loop and not self._loop.is_closed():
                import asyncio
                asyncio.run_coroutine_threadsafe(
                    self._async_remove(name),
                    self._loop,
                )

    async def _async_remove(self, name: str) -> None:
        self.on_agent_removed(name)


class _AgentFileHandler(FileSystemEventHandler):
    """Watches for YAML file changes in agents/ directories."""

    def __init__(self, reloader: AgentHotReloader) -> None:
        self.reloader = reloader

    def on_created(self, event: FileCreatedEvent) -> None:
        if not event.is_directory:
            self.reloader.handle_file_change(Path(event.src_path))

    def on_modified(self, event: FileModifiedEvent) -> None:
        if not event.is_directory:
            self.reloader.handle_file_change(Path(event.src_path))

    def on_deleted(self, event: FileDeletedEvent) -> None:
        if not event.is_directory:
            self.reloader.handle_file_deletion(Path(event.src_path))
