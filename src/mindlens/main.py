"""MindLens main entry point — boots all systems."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from mindlens.agents.agent_architect import AgentArchitect
from mindlens.agents.agent_librarian import AgentLibrarian
from mindlens.agents.agent_optimizer import AgentOptimizer
from mindlens.agents.base import AgentContext, AgentRegistry
from mindlens.agents.chief_of_staff import ChiefOfStaff
from mindlens.agents.workspace_manager import WorkspaceManager
from mindlens.agents.session_observer import SessionObserver
from mindlens.agents.efficiency_analyst import EfficiencyAnalyst
from mindlens.agents.reflector import Reflector
from mindlens.agents.memory_manager import MemoryManager
from mindlens.agents.test_runner import TestRunner
from mindlens.agents.bug_hunter import BugHunter
from mindlens.agents.security_red_team import SecurityRedTeam
from mindlens.agents.code_agent import CodeAgent
from mindlens.agents.yaml_agent import YamlAgent, discover_yaml_agents
from mindlens.core.config import Config
from mindlens.core.db import init_core_db, init_workspace_db, record_agent_run
from mindlens.core.event_bus import Event, EventBus
from mindlens.core.file_watcher import FileWatcher
from mindlens.core.hot_reload import AgentHotReloader, AgentDefinition
from mindlens.core.llm import LLMClient
from mindlens.core.scheduler import Scheduler
from mindlens.core.telegram import TelegramBot
from mindlens.pipelines.raw_to_wiki import run_pipeline
from mindlens.workspaces.registry import WorkspaceRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


class MindLens:
    """The main MindLens runtime — boots all systems and connects them."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.event_bus = EventBus()
        self.llm = LLMClient(
            api_key=config.llm_api_key,
            model=config.llm_model,
            base_url=config.llm_base_url,
        )
        self.registry = AgentRegistry()
        self.workspace_registry = WorkspaceRegistry(config.vault_path)
        self.telegram = TelegramBot(config, self.event_bus)
        self.file_watcher = FileWatcher(self.event_bus, config.vault_path)
        self.scheduler = Scheduler(config.vault_path, self._handle_scheduled_task, agent_discoverer=discover_yaml_agents)
        self.hot_reloader = AgentHotReloader(
            vault_path=config.vault_path,
            on_agent_added=self._on_agent_added,
            on_agent_changed=self._on_agent_changed,
            on_agent_removed=self._on_agent_removed,
        )

        self._core_db = None
        self._workspace_dbs: dict[str, object] = {}

    async def boot(self) -> None:
        """Boot all MindLens systems."""
        # Single-instance guard: PID lockfile
        import os, signal
        lockfile = Path("/tmp/mindlens.pid")
        if lockfile.exists():
            try:
                old_pid = int(lockfile.read_text().strip())
                os.kill(old_pid, 0)  # check if alive
                logger.error("MindLens already running (PID %d). Exiting.", old_pid)
                sys.exit(1)
            except (ValueError, ProcessLookupError, PermissionError):
                pass  # stale lockfile, overwrite below
        lockfile.write_text(str(os.getpid()))
        self._lockfile = lockfile

        logger.info("🧠 MindLens booting...")

        # 1. Init databases
        self._core_db = await init_core_db(self.config.core_db_path)

        # 2. Discover and load workspaces
        workspaces = self.workspace_registry.load_all()
        for name, ws in workspaces.items():
            logger.info("  Workspace: %s — %s", name, ws.mission[:60] if ws.mission else "(no mission)")
            self._workspace_dbs[name] = await init_workspace_db(
                self.config.workspace_db_path(name)
            )

        # 3. Register agents
        self._register_agents()

        # 4. Subscribe to events
        self._setup_event_handlers()

        # 5. Discover event-driven agent triggers from YAML definitions
        self._setup_yaml_event_triggers()

        # 6. Start file watcher (pass the running loop)
        loop = asyncio.get_running_loop()
        self.file_watcher.start(loop=loop)

        # 6b. Start agent hot-reloader
        self.hot_reloader.start(loop=loop)

        # 6. Start Telegram bot
        await self.telegram.start()

        # 7. Start scheduler (background task)
        asyncio.create_task(self.scheduler.start())

        logger.info("🧠 MindLens is online. %d workspaces, %d agents.",
                     len(workspaces), len(self.registry.list_agents()))

        # Keep the event loop running — wait forever
        try:
            await asyncio.Event().wait()
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("🧠 MindLens shutting down...")
        self.scheduler.stop()
        self.hot_reloader.stop()
        self.file_watcher.stop()
        await self.telegram.stop()
        await self.llm.close()
        if self._core_db:
            await self._core_db.close()
        for db in self._workspace_dbs.values():
            await db.close()
        # Remove PID lockfile
        lockfile = getattr(self, "_lockfile", None)
        if lockfile and lockfile.exists():
            try:
                lockfile.unlink()
            except OSError:
                pass
        logger.info("🧠 MindLens stopped.")

    # --- Hot-reload callbacks ---

    def _on_agent_added(self, defn: AgentDefinition) -> None:
        """Called when a new YAML agent definition is created."""
        logger.info("🔥 Hot-reload: new agent '%s'", defn.name)

        # Register as YAML agent
        from mindlens.agents.yaml_agent import YamlAgent
        if defn.name not in self.registry._agents:
            self.registry._agents[defn.name] = type(
                f"YamlAgent_{defn.name}",
                (YamlAgent,),
                {"_yaml_path": defn.path, "name": defn.name, "description": defn.description, "capabilities": defn.capabilities},
            )

        # Subscribe to events
        for event_topic in defn.events:
            self.event_bus.subscribe(
                event_topic,
                self._make_yaml_event_handler(defn.name, event_topic),
            )
            logger.info("  Subscribed: %s → %s", event_topic, defn.name)

        # Reload scheduler
        self.scheduler.load_tasks()

        # Notify via Telegram
        asyncio.create_task(self.telegram.send_message(
            f"🔥 Nieuwe agent actief: {defn.name}\n{defn.description}"
        ))

    def _on_agent_changed(self, defn: AgentDefinition) -> None:
        """Called when a YAML agent definition is modified."""
        logger.info("🔄 Hot-reload: agent '%s' changed", defn.name)

        # Re-register
        from mindlens.agents.yaml_agent import YamlAgent
        self.registry._agents[defn.name] = type(
            f"YamlAgent_{defn.name}",
            (YamlAgent,),
            {"_yaml_path": defn.path, "name": defn.name, "description": defn.description, "capabilities": defn.capabilities},
        )

        # Reload scheduler
        self.scheduler.load_tasks()

    def _on_agent_removed(self, name: str) -> None:
        """Called when a YAML agent definition is deleted."""
        logger.info("❌ Hot-reload: agent '%s' removed", name)

        # Unregister
        if name in self.registry._agents:
            del self.registry._agents[name]

        # Reload scheduler
        self.scheduler.load_tasks()

        # Notify
        asyncio.create_task(self.telegram.send_message(
            f"❌ Agent verwijderd: {name}"
        ))

    async def _handle_scheduled_task(self, agent_name: str, workspace: str, message: str) -> None:
        """Execute a scheduled task by running an agent."""
        agent = self.registry.create(
            agent_name,
            llm=self.llm,
            event_bus=self.event_bus,
            config=self.config,
        )
        if not agent:
            logger.error("Scheduled task: agent '%s' not found", agent_name)
            return

        context = AgentContext(task=message, workspace=workspace)
        result = await agent.run(context)

        # Find the task's notification level
        notify = "summary"  # default
        for task in self.scheduler._tasks:
            if task.message == message and task.workspace == workspace:
                notify = task.notify
                break

        if notify == "silent":
            logger.info("Scheduled task '%s' completed (silent)", agent_name)
        elif notify == "full":
            await self.telegram.send_message(result.output)
        elif notify == "result":
            # Only notify on errors or meaningful outcomes
            if not result.success:
                await self.telegram.send_message(f"❌ {agent_name} failed:\n{result.output[:500]}")
            else:
                # Extract issue references from output (closes #N, fix #N, etc.)
                import re as _re
                closed = _re.findall(r'(?:closes|close|fix(?:es)?)\s+#(\d+)', result.output, _re.IGNORECASE)
                if closed:
                    issue_list = ", ".join(f"#{n}" for n in closed)
                    await self.telegram.send_message(f"🔧 {agent_name}: opgelost {issue_list}")
                else:
                    logger.info("Scheduled task '%s' completed (result: no issues closed)", agent_name)
        else:  # summary
            await self.telegram.send_message(f"✅ {agent_name} done ({workspace})")

    def _register_agents(self) -> None:
        """Register all core agents + discover YAML agents from vault."""
        # Core Python agents
        core_agents = [
            ChiefOfStaff,
            WorkspaceManager,
            AgentArchitect,
            AgentOptimizer,
            AgentLibrarian,
            SessionObserver,
            EfficiencyAnalyst,
            Reflector,
            MemoryManager,
            TestRunner,
            BugHunter,
            SecurityRedTeam,
            CodeAgent,
        ]
        for agent_cls in core_agents:
            self.registry.register(agent_cls)

        # Discover YAML-driven agents from vault
        yaml_paths = discover_yaml_agents(self.config.vault_path)
        for yaml_path in yaml_paths:
            try:
                # Create a temporary instance to get the name
                temp = YamlAgent(yaml_path=yaml_path, llm=self.llm, event_bus=self.event_bus, config=self.config)
                # Register by name — the registry stores the class, we create instances on demand
                if temp.name not in self.registry._agents:
                    # Store the YAML path for lazy instantiation
                    self.registry._agents[temp.name] = type(
                        f"YamlAgent_{temp.name}",
                        (YamlAgent,),
                        {"_yaml_path": yaml_path, "name": temp.name, "description": temp.description, "capabilities": temp.capabilities},
                    )
                    logger.info("Registered YAML agent: %s from %s", temp.name, yaml_path.name)
            except Exception as e:
                logger.warning("Failed to register YAML agent from %s: %s", yaml_path, e)

    def _setup_event_handlers(self) -> None:
        """Set up event subscriptions."""
        # Chief of Staff handles telegram messages
        self.event_bus.subscribe("telegram.message", self._handle_telegram_message)

        # Agent routing events (from CoS after streaming completes)
        self.event_bus.subscribe("agent.route", self._handle_agent_route)

        # File watcher triggers pipeline (creation AND modification)
        self.event_bus.subscribe("raw_file.created", self._handle_raw_file)
        self.event_bus.subscribe("raw_file.modified", self._handle_raw_file)

        # Log all events
        self.event_bus.subscribe("*", self._log_event)

    def _setup_yaml_event_triggers(self) -> None:
        """Discover event subscriptions from YAML agent definitions."""
        import yaml as _yaml

        yaml_paths = discover_yaml_agents(self.config.vault_path)
        for yaml_path in yaml_paths:
            try:
                data = _yaml.safe_load(yaml_path.read_text()) or {}
                events = data.get("events") or []
                if not events:
                    continue

                agent_name = data.get("name", yaml_path.stem)
                for event_topic in events:
                    self.event_bus.subscribe(
                        event_topic,
                        self._make_yaml_event_handler(agent_name, event_topic),
                    )
                    logger.info("YAML event trigger: %s → %s", event_topic, agent_name)

            except Exception as e:
                logger.debug("Failed to parse YAML events from %s: %s", yaml_path, e)

    def _make_yaml_event_handler(self, agent_name: str, event_topic: str):
        """Create an event handler for a YAML agent trigger."""
        async def handler(event: Event) -> None:
            logger.info("Event %s triggered YAML agent: %s", event_topic, agent_name)

            agent = self.registry.create(
                agent_name,
                llm=self.llm,
                event_bus=self.event_bus,
                config=self.config,
            )
            if not agent:
                logger.warning("YAML agent '%s' not found for event %s", agent_name, event_topic)
                return

            # Build task from event data
            task = f"Event '{event_topic}' ontvangen van {event.source}. Data: {json.dumps(event.data)[:500]}"
            context = AgentContext(task=task, workspace=event.data.get("workspace"))

            try:
                result = await agent.run(context)

                # Check notification level from YAML
                data = _yaml.safe_load(agent.yaml_path.read_text()) if hasattr(agent, 'yaml_path') else {}
                notify = (data or {}).get("notify", "summary") if data else "summary"

                if notify == "full":
                    await self.telegram.send_message(result.output)
                elif notify == "summary":
                    await self.telegram.send_message(f"✅ {agent_name} triggered by {event_topic}")
                # silent = no notification

            except Exception:
                logger.exception("YAML agent %s failed on event %s", agent_name, event_topic)

        return handler

    async def _handle_telegram_message(self, event: Event) -> None:
        """Stream CoS response to Telegram. Routing handled via event bus."""
        text = event.data.get("text", "")
        workspace = event.data.get("workspace", "HQ")
        logger.info("Processing Telegram message: %r", text[:80])

        try:
            cos = self.registry.create(
                "chief_of_staff",
                llm=self.llm,
                event_bus=self.event_bus,
                config=self.config,
            )
            if not cos:
                await self.telegram.send_message("Error: Chief of Staff niet beschikbaar.")
                return

            context = AgentContext(task=text, workspace=workspace)

            # Stream response — routing is handled via event bus after stream
            await self.telegram.stream_message(
                cos.run_streaming(context),
                workspace,
            )

            # Publish agent run event (triggers YAML agents)
            await self.event_bus.publish(Event(
                topic="agent_run.completed",
                source="chief_of_staff",
                data={"workspace": workspace, "task": text, "success": True},
            ))

        except Exception:
            logger.exception("Telegram message handler failed")
            await self.telegram.send_message("❌ Fout bij verwerken van je bericht.")
            await self.event_bus.publish(Event(
                topic="agent_run.failed",
                source="chief_of_staff",
                data={"workspace": workspace, "task": text, "success": False},
            ))

    async def _handle_agent_route(self, event: Event) -> None:
        """Handle routing events from Chief of Staff."""
        route_data = event.data
        logger.info("Routing to %s in [%s]", route_data.get("target_agent"), route_data.get("target_workspace"))
        await self._handle_routed_task_streaming(route_data)

    async def _stream_text(self, text: str):
        """Yield a single text as one chunk (for stream_message compatibility)."""
        yield text

    async def _handle_routed_task_streaming(self, route_data: dict) -> None:
        """Handle a routed task with streaming output."""
        target_agent = route_data.get("target_agent")
        target_workspace = route_data.get("target_workspace", "HQ")
        task = route_data.get("task", "")

        if not target_agent:
            await self.telegram.send_message("No target agent specified.")
            return

        agent = self.registry.create(
            target_agent,
            llm=self.llm,
            event_bus=self.event_bus,
            config=self.config,
        )
        if not agent:
            available = ", ".join(a["name"] for a in self.registry.list_agents())
            await self.telegram.send_message(f"Agent '{target_agent}' not found. Available: {available}")
            return

        # Show processing indicator immediately
        context = AgentContext(task=task, workspace=target_workspace)

        # For agents that produce instant results (session agent, optimizer, etc.)
        # show ⏳ then the result. For LLM-based agents, stream.
        if hasattr(agent, 'run_streaming'):
            # Agent supports streaming
            await self.telegram.stream_message(
                agent.run_streaming(context),
                target_workspace,
            )
        else:
            # Instant agent — show processing, then result
            processing_msg = await self.telegram._app.bot.send_message(
                chat_id=self.config.telegram_user_id,
                text="⏳",
            )
            result = await agent.run(context)
            try:
                await processing_msg.edit_text(self.telegram._format_for_telegram(result.output[:4096]))
            except Exception:
                await self.telegram.send_message(result.output)

    async def _handle_raw_file(self, event: Event) -> None:
        """Handle new raw file — run the knowledge pipeline."""
        logger.info("HANDLER ENTERED: raw_file event: %s", event.data)
        workspace_name = event.data.get("workspace", "")
        file_path = event.data.get("file_path", "")

        if not workspace_name or not file_path:
            logger.warning("Raw file event missing data: %s", event.data)
            return

        logger.info("Processing new raw file: %s in %s", file_path, workspace_name)

        try:
            await self.telegram.send_message(
                f"📥 New file detected: {Path(file_path).name}. Processing...",
                workspace_name,
            )
        except Exception as e:
            logger.exception("Failed to send Telegram notification: %s", e)

        try:
            ws = self.workspace_registry.load(workspace_name)
            wiki_pages = [p.stem for p in ws.wiki_pages()]

            result = await run_pipeline(
                llm=self.llm,
                source_path=Path(file_path),
                workspace_path=ws.path,
                existing_wiki=wiki_pages,
            )

            wiki_content = result.get("wiki_content", "")
            if wiki_content:
                # Write wiki page
                source_name = Path(file_path).stem
                wiki_path = ws.path / "wiki" / f"{source_name}.md"
                wiki_path.write_text(wiki_content)

                await self.telegram.send_message(
                    f"✅ Wiki page created: wiki/{source_name}.md\n"
                    f"Links: {', '.join(result.get('wikilinks', []))}",
                    workspace_name,
                )

                # Publish event for librarian to potentially extract skills
                await self.event_bus.publish(Event(
                    topic="pipeline.completed",
                    source="raw_to_wiki",
                    data={
                        "workspace": workspace_name,
                        "source": file_path,
                        "wiki_path": str(wiki_path),
                        "wikilinks": result.get("wikilinks", []),
                    },
                ))
            else:
                await self.telegram.send_message(
                    f"⚠️ Could not generate wiki page for {Path(file_path).name}.",
                    workspace_name,
                )

        except Exception as e:
            logger.exception("Pipeline failed for %s", file_path)
            await self.telegram.send_message(
                f"❌ Error processing {Path(file_path).name}: {e}",
                workspace_name,
            )

    async def _log_event(self, event: Event) -> None:
        """Log all events to the core database."""
        if self._core_db:
            try:
                import json
                await self._core_db.execute(
                    "INSERT INTO events (topic, source, data) VALUES (?, ?, ?)",
                    (event.topic, event.source, json.dumps(event.data)),
                )
                await self._core_db.commit()
            except Exception:
                pass  # Don't let logging failures break the system


def run() -> None:
    """Entry point for `mindlens` CLI command."""
    config = Config.from_env()

    if not config.telegram_token:
        print("Error: MINDLENS_TELEGRAM_TOKEN not set in .env")
        sys.exit(1)
    if not config.llm_api_key:
        print("Error: MINDLENS_LLM_API_KEY not set in .env")
        sys.exit(1)

    app = MindLens(config)

    try:
        asyncio.run(app.boot())
    except KeyboardInterrupt:
        logger.info("Interrupted. Shutting down...")
        asyncio.run(app.shutdown())
