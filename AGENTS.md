# AGENTS.md — MindLens Codebase Guidelines

This file governs all AI coding assistants working in the MindLens Python codebase.

## Project Overview

MindLens is an AI-native holding company OS. It manages autonomous workspaces, each with knowledge bases, agent swarms, and code repos. Users interact via Telegram using natural language.

## Architecture

- **Code** (`~/projects/mindlens/`): Python source, git repo, this file
- **Vault** (Proton Drive `mindlens/`): Obsidian knowledge base, agent definitions, skills, ADRs, constitutions
- **Connection**: `.env` has `MINDLENS_VAULT_PATH` pointing to vault

## Code Conventions

- Python 3.12+
- `uv` for package management
- LangGraph for agent pipelines
- Async/await everywhere
- Type hints on all public functions
- Docstrings on all public classes
- Dutch language for user-facing messages and agent system prompts

## Directory Structure

```
src/mindlens/
├── core/              # Foundation: config, LLM, event bus, DB, telegram, scheduler, hot-reload
├── agents/            # Agent base class + Python agents
│   ├── base.py        # Agent ABC, AgentRegistry, scope-aware methods
│   ├── yaml_agent.py  # Generic YAML-driven agent runner
│   ├── chief_of_staff.py
│   ├── workspace_manager.py
│   ├── code_agent.py  # Minimal coding agent (pi.dev style)
│   └── ...
├── pipelines/         # LangGraph raw→wiki pipeline
│   ├── raw_to_wiki.py
│   └── nodes/
└── workspaces/        # Workspace runtime
```

## Agent System

Two types of agents:

1. **Python agents** — defined in `src/mindlens/agents/*.py`, registered in `main.py`
2. **YAML agents** — defined in vault `agents/*.yaml`, auto-discovered at boot and hot-reloaded

Adding a new agent = adding a YAML file to the vault. No Python code needed.

## Key Design Decisions

See `docs/adr/CONTEXT.md` for all ADRs. Critical ones:
- ADR-001: Self-contained architecture (vault vs code split)
- ADR-007: Agent scope rules (global vs workspace)
- ADR-010: Dynamic agent definitions (hot-reload)

## Event System

All communication via pub/sub event bus:
- `telegram.message` → Chief of Staff
- `raw_file.created/modified` → pipeline
- `agent_run.completed/failed` → memory_manager, bug_hunter
- `skill.extracted` → reflector
- YAML agents subscribe to events via `events:` field

## Scheduler

Discovers tasks from:
1. `tasks.yaml` (root + per-workspace)
2. YAML agents with `schedule:` field

## Self-Improvement

Cortex workspace agents (YAML-driven):
- Session Observer, Efficiency Analyst, Reflector, Memory Manager
- Bug Hunter, Security Red Team, Architecture Health, Feedback Loop Auditor

All operate at global scope. Never modify workspace-specific content.

## Safety

- Code changes require human approval
- Never commit `.env` or secrets
- Never delete ADRs (deprecate instead)
- YAML agents cannot modify their own system_prompt
- Scope enforcement: workspace agents cannot access other workspaces

## Running

```bash
uv sync                           # Install dependencies
uv run mindlens                   # Start MindLens
uv run mindlens-cli status        # CLI status check
```

## Testing

```bash
uv run python -c "import mindlens; print('OK')"  # Smoke test
```
