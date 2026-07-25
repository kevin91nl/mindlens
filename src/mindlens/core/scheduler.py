"""Scheduled task runner — executes agent tasks at configured times."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Coroutine

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """A task that runs at a scheduled time or via an event trigger."""
    name: str
    schedule: str  # cron expression: "minute hour day_of_month month day_of_week" (empty if trigger-only)
    agent: str
    workspace: str
    message: str
    enabled: bool = True
    notify: str = "summary"  # "silent", "summary", "full"
    trigger: str = ""              # bash command — exit 0 = work exists, exit 1 = idle
    trigger_interval: int = 30     # seconds between trigger checks

    def matches_now(self, minute: int, hour: int, day: int, month: int, weekday: int) -> bool:
        """Check if this task should run now based on cron expression."""
        parts = self.schedule.split()
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

    def __init__(self, vault_path: Path, handler: TaskHandler) -> None:
        self.vault_path = vault_path
        self.handler = handler
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
        from mindlens.agents.yaml_agent import discover_yaml_agents

        tasks = []
        yaml_paths = discover_yaml_agents(self.vault_path)

        for yaml_path in yaml_paths:
            try:
                data = yaml.safe_load(yaml_path.read_text()) or {}
                schedule = data.get("schedule", "")
                trigger = data.get("trigger", "")

                # Agent needs at least a schedule OR a trigger
                if not schedule and not trigger:
                    continue

                name = data.get("name", yaml_path.stem)
                workspace = "Cortex" if "Cortex" in str(yaml_path) else "HQ"
                notify = data.get("notify", "summary")

                # Check if this task already exists in tasks.yaml
                existing_names = {t.name for t in self._tasks}
                if name in existing_names:
                    continue

                tasks.append(ScheduledTask(
                    name=name,
                    schedule=schedule,
                    agent=name,
                    workspace=workspace,
                    message=f"Voer {name} taak uit: {data.get('description', '')}",
                    enabled=True,
                    notify=notify,
                    trigger=trigger,
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
            task = ScheduledTask(
                name=t["name"],
                schedule=t["schedule"],
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
        for task in self._tasks:
            if task.enabled and task.trigger and task.name not in self._trigger_tasks:
                logger.info("Spawning trigger agent: %s (every %ds)", task.name, task.trigger_interval)
                self._trigger_locks[task.name] = asyncio.Lock()
                self._trigger_tasks[task.name] = asyncio.create_task(self._run_trigger_loop(task))

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
            try:
                async with lock:
                    await self.handler(task.agent, task.workspace, task.message)
                logger.info(
                    "Task completed: %s (correlation_id=%s)",
                    task.name, correlation_id,
                )
            except Exception:
                logger.exception(
                    "Scheduled task %s failed (workspace=%s, correlation_id=%s, message=%s)",
                    task.name, task.workspace, correlation_id, task.message,
                )

        # Launch all tasks concurrently
        await asyncio.gather(
            *[_run_with_isolation(task) for task in tasks_to_run],
            return_exceptions=True,
        )

    async def _run_trigger_loop(self, task: ScheduledTask) -> None:
        """Trigger-based agent loop: run deterministic check, invoke agent only when work exists."""
        import subprocess as _sp
        import time as _time
        logger.info("Trigger agent '%s' started (polling every %ds)", task.name, task.trigger_interval)

        while self._running:
            try:
                # Deterministic check — no LLM, no tokens
                result = _sp.run(
                    task.trigger, shell=True, capture_output=True,
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
                    except Exception:
                        logger.exception(
                            "Trigger agent '%s' failed (workspace=%s, trigger_cmd=%s, message=%s)",
                            task.name, task.workspace, task.trigger, task.message,
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
                    task.name, task.workspace, task.trigger,
                )
                await asyncio.sleep(task.trigger_interval)
            except Exception:
                logger.exception(
                    "Trigger '%s': check failed (workspace=%s, trigger_cmd=%s)",
                    task.name, task.workspace, task.trigger,
                )
                await asyncio.sleep(task.trigger_interval)

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        logger.info("Scheduler stopped")
