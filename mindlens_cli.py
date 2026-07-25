"""MindLens CLI — manage workspaces, tasks, issues, and agents."""

from __future__ import annotations

import sys
import os
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent / "src"))


def load_config():
    """Load config from .env."""
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    from mindlens.core.config import Config
    return Config.from_env()


def cmd_init(args):
    """Initialize a MindLens vault."""
    config = load_config()
    vault = config.vault_path

    print(f"🧠 Initializing MindLens vault at: {vault}")

    # Create directory structure
    dirs = [
        vault / "agents",
        vault / "docs" / "adr",
        vault / ".mindlens" / "skills",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        print(f"  ✅ {d.relative_to(vault)}")

    # Create root CONTEXT.md if it doesn't exist
    context_md = vault / "CONTEXT.md"
    if not context_md.exists():
        context_md.write_text("# CONTEXT.md — MindLens Decision Index\n\nAll architectural decisions are recorded as ADRs in [`docs/adr/`](docs/adr/).\n\nNew decisions go through `docs/adr/CONTEXT.md`.\n")
        print(f"  ✅ CONTEXT.md")

    # Create root tasks.yaml if it doesn't exist
    tasks_yaml = vault / "tasks.yaml"
    if not tasks_yaml.exists():
        tasks_yaml.write_text("# Global Scheduled Tasks\ntasks:\n  - name: daily_briefing\n    schedule: \"0 9 * * *\"\n    agent: chief_of_staff\n    workspace: HQ\n    message: \"Geef een dagelijks overzicht van alle werkruimtes.\"\n    enabled: true\n    notify: full\n")
        print(f"  ✅ tasks.yaml")

    # Create root issues.yaml if it doesn't exist
    issues_yaml = vault / "issues.yaml"
    if not issues_yaml.exists():
        issues_yaml.write_text("# Global Issues\nissues: []\n")
        print(f"  ✅ issues.yaml")

    # Create agents index
    agents_index = vault / "agents" / "INDEX.md"
    if not agents_index.exists():
        agents_index.write_text("# Agent Definitions\n\nGlobal agents available to all workspaces.\n")
        print(f"  ✅ agents/INDEX.md")

    print(f"\n✅ Vault initialized! Add workspaces with: mindlens-cli workspace create <name>")


def cmd_start(args):
    """Start MindLens."""
    config = load_config()

    if not config.telegram_token:
        print("❌ MINDLENS_TELEGRAM_TOKEN not set in .env")
        sys.exit(1)
    if not config.llm_api_key:
        print("❌ MINDLENS_LLM_API_KEY not set in .env")
        sys.exit(1)

    print("🧠 Starting MindLens...")
    from mindlens.main import MindLens
    import asyncio

    app = MindLens(config)
    try:
        asyncio.run(app.boot())
    except KeyboardInterrupt:
        print("\n🧠 MindLens stopped.")
        asyncio.run(app.shutdown())


def cmd_workspace(args):
    """Manage workspaces."""
    config = load_config()
    vault = config.vault_path

    if args.subcmd == "create":
        name = args.name
        ws_path = vault / name
        if ws_path.exists():
            print(f"❌ Workspace '{name}' already exists")
            sys.exit(1)

        # Create structure
        dirs = [
            ws_path / "raw",
            ws_path / "wiki",
            ws_path / "agents",
            ws_path / ".mindlens" / "skills",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

        # Constitution
        (ws_path / "constitution.md").write_text(
            f"# {name} — Constitution\n\n## Mission\n\nTODO: Define the mission for this workspace.\n\n## Priorities\n\n1. Accuracy\n2. Speed\n3. Completeness\n\n## Autonomy Level\n\nMedium\n"
        )

        # Tasks
        (ws_path / "tasks.yaml").write_text(f"# {name} Scheduled Tasks\ntasks: []\n")

        # Issues
        (ws_path / "issues.yaml").write_text(f"# {name} Issues\nissues: []\n")

        # Repos
        (ws_path / "repos.yaml").write_text("repos: []\n")

        print(f"✅ Workspace '{name}' created at {ws_path}")
        print(f"   Edit {ws_path / 'constitution.md'} to set the mission")

    elif args.subcmd == "list":
        workspaces = []
        for item in sorted(vault.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                constitution = item / "constitution.md"
                mission = ""
                if constitution.exists():
                    for line in constitution.read_text().splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and not line.startswith("-") and not line.startswith("**"):
                            mission = line
                            break
                workspaces.append((item.name, mission or "(no mission)"))

        if not workspaces:
            print("No workspaces found. Create one with: mindlens-cli workspace create <name>")
            return

        print("📂 Workspaces:\n")
        for name, mission in workspaces:
            print(f"  • {name}: {mission}")


def cmd_issues(args):
    """Manage issues."""
    config = load_config()
    vault = config.vault_path
    import yaml

    ws = args.workspace or "global"
    if ws == "global":
        issues_path = vault / "issues.yaml"
    else:
        issues_path = vault / ws / "issues.yaml"

    if args.subcmd == "list":
        if not issues_path.exists():
            print(f"No issues.yaml in {ws}")
            return

        data = yaml.safe_load(issues_path.read_text()) or {}
        issues = data.get("issues") or []

        if args.status:
            issues = [i for i in issues if i.get("status") == args.status]

        if not issues:
            print(f"No issues{f' ({args.status})' if args.status else ''} in {ws}")
            return

        icons = {"backlog": "📥", "todo": "📝", "in_progress": "🔄", "review": "👀", "done": "✅", "blocked": "🚫"}
        print(f"📋 Issues in {ws}:\n")
        for i in issues:
            icon = icons.get(i.get("status", ""), "❓")
            print(f"  {icon} {i['id']} | {i.get('title', '?')} → {i.get('assignee', '?')}")

    elif args.subcmd == "add":
        if not issues_path.exists():
            issues_path.write_text("issues: []\n")

        data = yaml.safe_load(issues_path.read_text()) or {}
        issues = data.get("issues") or []

        prefix = ws.upper()[:3] if ws != "global" else "MIND"
        next_num = len(issues) + 1
        issue_id = f"{prefix}-{next_num:03d}"

        from datetime import date
        issue = {
            "id": issue_id,
            "title": args.title,
            "status": "backlog",
            "priority": args.priority or "medium",
            "assignee": args.assignee or "",
            "description": args.description or "",
            "created": str(date.today()),
            "updated": str(date.today()),
        }
        issues.append(issue)
        data["issues"] = issues
        issues_path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
        print(f"✅ Issue {issue_id} created: {args.title}")


def cmd_tasks(args):
    """Manage tasks."""
    config = load_config()
    vault = config.vault_path
    import yaml

    ws = args.workspace or "global"
    if ws == "global":
        tasks_path = vault / "tasks.yaml"
    else:
        tasks_path = vault / ws / "tasks.yaml"

    if args.subcmd == "list":
        if not tasks_path.exists():
            print(f"No tasks.yaml in {ws}")
            return

        data = yaml.safe_load(tasks_path.read_text()) or {}
        tasks = data.get("tasks") or []

        if not tasks:
            print(f"No tasks in {ws}")
            return

        print(f"⏰ Tasks in {ws}:\n")
        for t in tasks:
            status = "✅" if t.get("enabled", True) else "⏸️"
            print(f"  {status} {t['name']} | {t['schedule']} | {t.get('agent', '?')}")


def cmd_status(args):
    """Show system status."""
    config = load_config()
    vault = config.vault_path

    print("🧠 MindLens Status\n")

    # Workspaces
    workspaces = [d.name for d in vault.iterdir() if d.is_dir() and not d.name.startswith(".")]
    print(f"📂 Workspaces: {len(workspaces)}")
    for ws in workspaces:
        print(f"  • {ws}")

    # Global tasks
    tasks_path = vault / "tasks.yaml"
    if tasks_path.exists():
        import yaml
        data = yaml.safe_load(tasks_path.read_text()) or {}
        tasks = data.get("tasks") or []
        enabled = sum(1 for t in tasks if t.get("enabled", True))
        print(f"\n⏰ Global tasks: {len(tasks)} ({enabled} enabled)")

    # Global issues
    issues_path = vault / "issues.yaml"
    if issues_path.exists():
        import yaml
        data = yaml.safe_load(issues_path.read_text()) or {}
        issues = data.get("issues") or []
        open_issues = [i for i in issues if i.get("status") not in ("done",)]
        print(f"📋 Global issues: {len(issues)} ({len(open_issues)} open)")

    # Agents
    agents_path = vault / "agents"
    if agents_path.exists():
        agents = list(agents_path.glob("*.yaml"))
        print(f"🤖 Global agents: {len(agents)}")

    print(f"\n💡 Start with: uv run mindlens-cli start")


def main():
    parser = argparse.ArgumentParser(
        prog="mindlens-cli",
        description="🧠 MindLens — AI-Native Holding Company OS",
    )
    subparsers = parser.add_subparsers(dest="command")

    # init
    subparsers.add_parser("init", help="Initialize vault structure")

    # start
    subparsers.add_parser("start", help="Start MindLens")

    # workspace
    ws_parser = subparsers.add_parser("workspace", help="Manage workspaces")
    ws_sub = ws_parser.add_subparsers(dest="subcmd")
    ws_create = ws_sub.add_parser("create", help="Create a workspace")
    ws_create.add_argument("name", help="Workspace name")
    ws_sub.add_parser("list", help="List workspaces")

    # issues
    issues_parser = subparsers.add_parser("issues", help="Manage issues")
    issues_sub = issues_parser.add_subparsers(dest="subcmd")
    issues_list = issues_sub.add_parser("list", help="List issues")
    issues_list.add_argument("--workspace", "-w", help="Workspace name")
    issues_list.add_argument("--status", "-s", help="Filter by status")
    issues_add = issues_sub.add_parser("add", help="Add an issue")
    issues_add.add_argument("--workspace", "-w", help="Workspace name")
    issues_add.add_argument("--title", "-t", required=True, help="Issue title")
    issues_add.add_argument("--priority", "-p", default="medium", help="Priority (low/medium/high/critical)")
    issues_add.add_argument("--assignee", "-a", help="Assignee agent name")
    issues_add.add_argument("--description", "-d", help="Description")

    # tasks
    tasks_parser = subparsers.add_parser("tasks", help="Manage tasks")
    tasks_sub = tasks_parser.add_subparsers(dest="subcmd")
    tasks_list = tasks_sub.add_parser("list", help="List tasks")
    tasks_list.add_argument("--workspace", "-w", help="Workspace name")

    # status
    subparsers.add_parser("status", help="Show system status")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "workspace":
        cmd_workspace(args)
    elif args.command == "issues":
        cmd_issues(args)
    elif args.command == "tasks":
        cmd_tasks(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
