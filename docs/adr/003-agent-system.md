# ADR-003: Agent System

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** Kevin

## Context

MindLens needs agents that can process knowledge, write code, manage workspaces, and communicate with each other. Agents must be manageable via natural language through Telegram. The system must support both knowledge processing (LangGraph pipelines) and code development (OpenCode-compatible).

## Decision

### Two agent categories

1. **Knowledge agents** — LangGraph pipeline nodes (reader, distiller, linker, reviewer)
2. **Code agents** — OpenCode-compatible coding agents with access to repos and vault

### Core agents (always present)

| Agent | Role |
|-------|------|
| **Chief of Staff** | Telegram interface, daily briefing, routing, natural language commands |
| **Agent Architect** | Designs new agents, generates prompts, creates agent configs |
| **Agent Optimizer** | Monitors performance, tracks tokens, suggests improvements |
| **Agent Librarian** | Version control for agent configs, skill extraction, rollback |
| **Workspace Manager** | Creates/manages workspaces and their agent swarms |

### Inter-agent communication: Event Bus

All agents communicate via a pub/sub event bus:
- Agents publish events: `"new_paper_ingested"`, `"code_change_proposed"`, `"quality_issue_found"`
- Agents subscribe to events they care about
- Core agents (Chief of Staff) see ALL events for briefing
- Inter-workspace communication goes through the Gateway (Chief of Staff)

### Agent definitions

Agents are defined in YAML files in `.mindlens/agents/`:

```yaml
name: code_agent
type: coder
backend: opencode
model: Xiaomi/MiMo-V2.5-Pro
skills:
  - global:*
  - workspace:*
instructions:
  - global:coding-standards.md
  - workspace:constitution.md
capabilities:
  - code_edit
  - terminal
  - git
  - file_read
  - vault_read
  - vault_search
```

### LangGraph pipeline

The raw→wiki pipeline is a LangGraph state machine:

```
raw file → Reader → Distiller → Linker → Reviewer → wiki page
                          ↑                    │
                          └── (revise if fails) ┘
```

Core provides `PipelineRunner` (generic executor). Workspaces configure which agents to use, prompts, and pipeline steps. Adding a new workspace = writing config, not code.

### Approval gates

- **Code changes**: Always require human approval. Bot shows diff via Telegram, Kevin approves/rejects.
- **Wiki writes**: Knowledge agents write freely. Code agents can only propose (human approves).
- **Agent creation/modification**: Always requires approval.

## Consequences

- **Pro:** Natural language management via Telegram.
- **Pro:** Agents can discover and use workspace knowledge.
- **Pro:** Event bus enables cross-workspace intelligence.
- **Con:** 4 core agents from day 1 is ambitious. Mitigated by phased sprint plan.
- **Con:** LangGraph has a learning curve. Worth it for future extensibility.
