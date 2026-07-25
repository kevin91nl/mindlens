"""Scheduled task runner — executes agent tasks at configured times."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

import yaml

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds
MAX_DELAY = 30.0  # seconds


@dataclass
class ScheduledTask:
    """A task that runs at scheduled times or via event triggers."""
    name: str
    schedules: list[str] = field(default_factory=list)  # cron expressions
    agent: str = ""
    workspace: str = ""
    message: str = ""
    enabled: bool = True
    notify: str = "summary"  # "silent", "summary", "full"
    triggers: list[str | dict] = field(default_factory=list)  # commands OR {type: watch, ...}
    trigger_interval: int = 30  # default seconds between command trigger checks

    def matches_now(self, minute: int, hour: int, day: int, month: int, weekday: int) -> bool:
        """Check if ANY of this task's schedules match now."""
        for schedule in self.schedules:
            if self._match_schedule(schedule, minute, hour, day, month, weekday):
                return True
        return False

    def _match_schedule(self, schedule: str, minute: int, hour: int, day: int, month: int, weekday: int) -> bool:
        """Check a single cron expression."""
        parts = schedule.split()
        if len(parts) != 5:
            return False
        checks = [
            (parts[0], minute),
            (parts[1], hour),
            (parts[2], day),
            (parts[3], month),
            (parts[4], weekday),
        ]
        for pattern, value in checks:
            if not self._match_field(pattern, value):
                return False
        return True

    @staticmethod
    def _match_field(pattern: str, value: int) -> bool:
        """Match a single cron field against a value."""
        if pattern == "*":
            return True
        if "/" in pattern:
            base, step = pattern.split("/")
            if base == "*":
                return value % int(step) == 0
            return value % int(step) == 0
        if "-" in pattern:
            start, end = pattern.split("-")
            return int(start) <= value <= int(end)
        if "," in pattern:
            return value in [int(x) for x in pattern.split(",")]
        return int(pattern) == value


TaskHandler = Callable[[str, str, str], Coroutine[Any, Any, None]]


class Scheduler:
    """Reads scheduled_tasks.yaml and triggers tasks at the right time."""

    def __init__(self, vault_path: Path, handler: TaskHandler, agent_discoverer: Callable[[Path], list[Path]] | None = None) -> None:
        self.vault_path = vault_path
        self.handler = handler
        self._agent_discoverer = agent_discoverer
        self._tasks: list[ScheduledTask] = []
        self._running = False
        self._trigger_tasks: dict[str, asyncio.Task] = {}  # name → asyncio.Task
        self._trigger_locks: dict[str, asyncio.Lock] = {}  # name → Lock
        self._workspace_locks: dict[str, asyncio.Lock] = {}  # workspace → Lock for isolation

    def load_tasks(self) -> list[ScheduledTask]:
        """Load tasks from global, per-workspace tasks.yaml, and YAML agent definitions."""
        self._tasks = []

        # Global tasks (tasks.yaml in vault root)
        global_file = self.vault_path / "tasks.yaml"
        self._tasks.extend(self._load_file(global_file, "global"))

        # Per-workspace tasks (tasks.yaml in workspace root)
        # Skip hidden dirs and the vault root's own tasks.yaml
        for item in self.vault_path.iterdir():
            if item.is_dir() and not item.name.startswith(".") and item.name != "scheduled":
                ws_file = item / "tasks.yaml"
                if ws_file.exists():
                    self._tasks.extend(self._load_file(ws_file, item.name))

        # YAML agents with schedule field
        self._tasks.extend(self._load_yaml_agent_tasks())

        enabled = sum(1 for t in self._tasks if t.enabled)
        logger.info("Loaded %d scheduled tasks (%d enabled)", len(self._tasks), enabled)
        return self._tasks

    def _load_yaml_agent_tasks(self) -> list[ScheduledTask]:
        """Discover YAML agents with schedule or trigger fields and create tasks."""
        if not self._agent_discoverer:
            return []

        tasks = []
        yaml_paths = self._agent_discoverer(self.vault_path)

        for yaml_path in yaml_paths:
            try:
                data = yaml.safe_load(yaml_path.read_text()) or {}
                name = data.get("name", yaml_path.stem)

                # Normalize schedules: string → [string], list → list, none → []
                raw_schedules = data.get("schedules") or data.get("schedule") or ""
                if isinstance(raw_schedules, str):
                    schedules = [raw_schedules] if raw_schedules else []
                elif isinstance(raw_schedules, list):
                    schedules = [s for s in raw_schedules if s]
                else:
                    schedules = []

                # Normalize triggers: string/dict → [item], list → list, none → []
                raw_triggers = data.get("triggers") or data.get("trigger") or ""
                if isinstance(raw_triggers, (str, dict)):
                    triggers = [raw_triggers] if raw_triggers else []
                elif isinstance(raw_triggers, list):
                    triggers = [t for t in raw_triggers if t]
                else:
                    triggers = []

                # Agent needs at least a schedule OR a trigger
                if not schedules and not triggers:
                    continue

                workspace = "Cortex" if "Cortex" in str(yaml_path) else "HQ"
                notify = data.get("notify", "summary")

                # Check if this task already exists in tasks.yaml
                existing_names = {t.name for t in self._tasks}
                if name in existing_names:
                    continue

                tasks.append(ScheduledTask(
                    name=name,
                    schedules=schedules,
                    agent=name,
                    workspace=workspace,
                    message=f"Voer {name} taak uit: {data.get('description', '')}",
                    enabled=True,
                    notify=notify,
                    triggers=triggers,
                    trigger_interval=int(data.get("trigger_interval", 30)),
                ))
            except Exception:
                continue

        return tasks

    def _load_file(self, path: Path, scope: str) -> list[ScheduledTask]:
        """Load tasks from a single YAML file."""
        if not path.exists():
            return []

        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            logger.exception("Failed to parse %s", path)
            return []

        tasks = []
        for t in data.get("tasks") or []:
            # Normalize schedule → schedules list
            raw_schedule = t.get("schedules") or t.get("schedule") or ""
            if isinstance(raw_schedule, str):
                schedules = [raw_schedule] if raw_schedule else []
            elif isinstance(raw_schedule, list):
                schedules = [s for s in raw_schedule if s]
            else:
                schedules = []
            task = ScheduledTask(
                name=t["name"],
                schedules=schedules,
                agent=t["agent"],
                workspace=t.get("workspace", scope if scope != "global" else "HQ"),
                message=t["message"],
                enabled=t.get("enabled", True),
                notify=t.get("notify", "summary"),
            )
            tasks.append(task)
        return tasks

    async def start(self) -> None:
        """Start the scheduler loop. Checks every minute + spawns continuous agents."""
        self._running = True
        self.load_tasks()
        logger.info("Scheduler started. Checking every 60s.")

        # Spawn trigger-based agents as persistent background tasks (skip if already running)
        loop = asyncio.get_running_loop()
        for task in self._tasks:
            if not task.enabled:
                continue
            if task.name not in self._trigger_locks:
                self._trigger_locks[task.name] = asyncio.Lock()
            for i, trigger in enumerate(task.triggers):
                trigger_key = f"{task.name}:trigger:{i}"
                if trigger_key in self._trigger_tasks:
                    continue
                if isinstance(trigger, dict) and trigger.get("type") == "watch":
                    logger.info("Spawning watch trigger: %s (paths=%s, debounce=%ds)",
                        task.name, trigger.get("paths"), trigger.get("debounce", 30))
                    self._setup_watch_trigger(task, trigger, loop)
                elif isinstance(trigger, str) and trigger:
                    logger.info("Spawning command trigger: %s (every %ds)", task.name, task.trigger_interval)
                    self._trigger_tasks[trigger_key] = asyncio.create_task(
                        self._run_trigger_loop(task, trigger))

        while self._running:
            try:
                await self._check_and_run()
            except Exception:
                logger.exception("Scheduler check failed")
            await asyncio.sleep(60)

    def _get_workspace_lock(self, workspace: str) -> asyncio.Lock:
        """Get or create a lock for a workspace to ensure isolation."""
        if workspace not in self._workspace_locks:
            self._workspace_locks[workspace] = asyncio.Lock()
        return self._workspace_locks[workspace]

    async def _check_and_run(self) -> None:
        """Check if any tasks should run now. Executes concurrently with workspace isolation."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        minute, hour, day, month, weekday = now.minute, now.hour, now.day, now.month, now.weekday()

        # Collect tasks that should run now
        tasks_to_run = []
        for task in self._tasks:
            if not task.enabled:
                continue
            if task.matches_now(minute, hour, day, month, weekday):
                tasks_to_run.append(task)

        if not tasks_to_run:
            return

        # Execute tasks concurrently, but serialize per-workspace
        async def _run_with_isolation(task: ScheduledTask) -> None:
            correlation_id = str(uuid.uuid4())[:8]
            lock = self._get_workspace_lock(task.workspace)
            logger.info(
                "Running scheduled task: %s (workspace=%s, correlation_id=%s)",
                task.name, task.workspace, correlation_id,
            )
            last_error = None
            for attempt in range(MAX_RETRIES):
                try:
                    async with lock:
                        await self.handler(task.agent, task.workspace, task.message)
                    logger.info(
                        "Task completed: %s (correlation_id=%s)",
                        task.name, correlation_id,
                    )
                    return
                except Exception as e:
                    last_error = e
                    if attempt < MAX_RETRIES - 1:
                        delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                        logger.warning(
                            "Scheduled task %s failed (attempt %d/%d, retrying in %.1fs): %s",
                            task.name, attempt + 1, MAX_RETRIES, delay, str(e),
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.exception(
                            "Scheduled task %s failed after %d attempts (workspace=%s, correlation_id=%s, message=%s)",
                            task.name, MAX_RETRIES, task.workspace, correlation_id, task.message,
                        )

        # Launch all tasks concurrently
        await asyncio.gather(
            *[_run_with_isolation(task) for task in tasks_to_run],
            return_exceptions=True,
        )

    async def _run_trigger_loop(self, task: ScheduledTask, trigger_cmd: str) -> None:
        """Trigger-based agent loop: run deterministic check, invoke agent only when work exists."""
        import subprocess as _sp
        import time as _time
        logger.info("Trigger agent '%s' started (polling every %ds, cmd=%s)", task.name, task.trigger_interval, trigger_cmd[:80])

        while self._running:
            try:
                # Deterministic check — no LLM, no tokens
                result = _sp.run(
                    trigger_cmd, shell=True, capture_output=True,
                    text=True, timeout=15,
                )
                has_work = result.returncode == 0

                if has_work:
                    logger.info("Trigger '%s': work detected, running agent", task.name)
                    lock = self._trigger_locks.get(task.name)
                    if lock and lock.locked():
                        logger.info("Trigger '%s': already running, skipping", task.name)
                        await asyncio.sleep(task.trigger_interval)
                        continue
                    for retry_attempt in range(MAX_RETRIES):
                        try:
                            start_time = _time.monotonic()
                            if lock:
                                async with lock:
                                    await self.handler(task.agent, task.workspace, task.message)
                            else:
                                await self.handler(task.agent, task.workspace, task.message)
                            elapsed = _time.monotonic() - start_time
                            logger.info(
                                "Trigger agent '%s' completed (workspace=%s, elapsed=%.1fs)",
                                task.name, task.workspace, elapsed,
                            )
                            break
                        except Exception as e:
                            if retry_attempt < MAX_RETRIES - 1:
                                delay = min(BASE_DELAY * (2 ** retry_attempt), MAX_DELAY)
                                logger.warning(
                                    "Trigger agent '%s' failed (attempt %d/%d, retrying in %.1fs): %s",
                                    task.name, retry_attempt + 1, MAX_RETRIES, delay, str(e),
                                )
                                await asyncio.sleep(delay)
                            else:
                                logger.exception(
                                    "Trigger agent '%s' failed after %d attempts (workspace=%s, trigger_cmd=%s, message=%s)",
                                    task.name, MAX_RETRIES, task.workspace, trigger_cmd, task.message,
                                )
                    # Short cooldown before re-checking to avoid tight loops
                    await asyncio.sleep(10)
                    continue
                else:
                    # No work — wait before checking again
                    await asyncio.sleep(task.trigger_interval)

            except _sp.TimeoutExpired:
                logger.warning(
                    "Trigger '%s': check timed out (workspace=%s, trigger_cmd=%s)",
                    task.name, task.workspace, trigger_cmd,
                )
                await asyncio.sleep(task.trigger_interval)
            except Exception:
                logger.exception(
                    "Trigger '%s': check failed (workspace=%s, trigger_cmd=%s)",
                    task.name, task.workspace, trigger_cmd,
                )
                await asyncio.sleep(task.trigger_interval)

    def _setup_watch_trigger(self, task: ScheduledTask, trigger_config: dict, loop: asyncio.AbstractEventLoop) -> None:
        """Set up a file-watch trigger using watchdog."""
        import time as _time
        from watchdog.observers import Observer as _Observer
        from watchdog.events import FileSystemEventHandler as _FSEH
        from watchdog.events import FileCreatedEvent, FileModifiedEvent

        paths = trigger_config.get("paths", [])
        debounce = trigger_config.get("debounce", 30)
        if isinstance(paths, str):
            paths = [paths]

        class _WatchHandler(_FSEH):
            def __init__(self, scheduler, task, debounce):
                self.scheduler = scheduler
                self.task = task
                self.debounce = debounce
                self._last_trigger = 0.0

            def _should_trigger(self, path):
                if Path(path).name.startswith(".") or Path(path).name.endswith(".tmp"):
                    return False
                now = _time.monotonic()
                if now - self._last_trigger < self.debounce:
                    return False
                self._last_trigger = now
                return True

            def on_created(self, event):
                if event.is_directory:
                    return
                if not self._should_trigger(event.src_path):
                    return
                logger.info("Watch trigger '%s': file created %s", self.task.name, event.src_path)
                asyncio.run_coroutine_threadsafe(self._run_task(event.src_path), loop)

            def on_modified(self, event):
                if event.is_directory:
                    return
                if not self._should_trigger(event.src_path):
                    return
                logger.info("Watch trigger '%s': file modified %s", self.task.name, event.src_path)
                asyncio.run_coroutine_threadsafe(self._run_task(event.src_path), loop)

            async def _run_task(self, src_path):
                lock = self.scheduler._trigger_locks.get(self.task.name)
                if lock and lock.locked():
                    logger.info("Watch trigger '%s': already running, skipping", self.task.name)
                    return
                for attempt in range(MAX_RETRIES):
                    try:
                        start = _time.monotonic()
                        msg = self.task.message + f"\nGewijzigd bestand: {src_path}"
                        if lock:
                            async with lock:
                                await self.scheduler.handler(self.task.agent, self.task.workspace, msg)
                        else:
                            await self.scheduler.handler(self.task.agent, self.task.workspace, msg)
                        logger.info("Watch trigger '%s' completed (%.1fs)", self.task.name, _time.monotonic() - start)
                        return
                    except Exception as e:
                        if attempt < MAX_RETRIES - 1:
                            delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                            logger.warning("Watch trigger '%s' failed (attempt %d/%d, retrying in %.1fs): %s",
                                self.task.name, attempt + 1, MAX_RETRIES, delay, e)
                            await asyncio.sleep(delay)
                        else:
                            logger.exception("Watch trigger '%s' failed after %d attempts", self.task.name, MAX_RETRIES)

        handler = _WatchHandler(self, task, debounce)
        observer = _Observer()
        for rel_path in paths:
            full_path = self.vault_path / rel_path
            if full_path.exists():
                observer.schedule(handler, str(full_path), recursive=True)
                logger.info("Watching %s for agent '%s'", full_path, task.name)
            else:
                logger.warning("Watch path does not exist: %s (agent '%s')", full_path, task.name)
        observer.start()
        if not hasattr(self, '_watch_observers'):
            self._watch_observers = []
        self._watch_observers.append(observer)

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        for obs in getattr(self, '_watch_observers', []):
            obs.stop()
            obs.join()
        logger.info("Scheduler stopped")
