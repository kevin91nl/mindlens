"""Scheduled task runner — executes agent tasks at configured times."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Coroutine

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """A task that runs at a scheduled time."""
    name: str
    schedule: str  # cron expression: "minute hour day_of_month month day_of_week"
    agent: str
    workspace: str
    message: str
    enabled: bool = True
    notify: str = "summary"  # "silent", "summary", "full"
    continuous: bool = False  # run as persistent background agent
    check_command: str = ""   # bash command to check if work exists (exit 0 = work, exit 1 = idle)

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
        """Discover YAML agents with schedule fields and create tasks."""
        from mindlens.agents.yaml_agent import discover_yaml_agents

        tasks = []
        yaml_paths = discover_yaml_agents(self.vault_path)

        for yaml_path in yaml_paths:
            try:
                data = yaml.safe_load(yaml_path.read_text()) or {}
                schedule = data.get("schedule")
                if not schedule:
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
        """Start the scheduler loop. Checks every minute."""
        self._running = True
        self.load_tasks()
        logger.info("Scheduler started. Checking every 60s.")

        while self._running:
            try:
                await self._check_and_run()
            except Exception:
                logger.exception("Scheduler check failed")
            await asyncio.sleep(60)

    async def _check_and_run(self) -> None:
        """Check if any tasks should run now."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        minute, hour, day, month, weekday = now.minute, now.hour, now.day, now.month, now.weekday()

        for task in self._tasks:
            if not task.enabled:
                continue
            if task.matches_now(minute, hour, day, month, weekday):
                logger.info("Running scheduled task: %s", task.name)
                try:
                    await self.handler(task.agent, task.workspace, task.message)
                except Exception:
                    logger.exception("Scheduled task %s failed", task.name)

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        logger.info("Scheduler stopped")
