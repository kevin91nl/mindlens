# ADR-007: Agent Scope & Permissions

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** Kevin

## Context

MindLens has global agents (Chief of Staff, Architect, Optimizer, Librarian, etc.) and per-workspace agents (e.g., HypothesisEvidenceTracker in PhD). Agents need to manage tasks, wikis, and other agents — but scope must be enforced to prevent cross-workspace interference.

## Decision

### Scope principle

**An agent's scope is determined by where it is defined.**

| Agent level | Defined in | Can modify |
|-------------|-----------|------------|
| **Global** | `/agents/*.yaml` | Everything: all workspaces, all tasks, all wikis, all agents |
| **Workspace** | `<Workspace>/agents/*.yaml` | Only that workspace's tasks, wiki, and agents |

### Resource permissions

| Resource | Global agents | Workspace agents |
|----------|--------------|-----------------|
| **Tasks** | `/tasks.yaml` + all `<Workspace>/tasks.yaml` | Only `<Workspace>/tasks.yaml` |
| **Wiki** | All `<Workspace>/wiki/*` | Only own `<Workspace>/wiki/*` |
| **Agents** | All `/agents/*.yaml` + all `<Workspace>/agents/*.yaml` | Only own `<Workspace>/agents/*.yaml` |
| **Constitutions** | All workspaces | Only own workspace |
| **Repos** | All repos in all workspaces | Only repos in own `repos.yaml` |
| **New workspaces** | ✅ Can create | ❌ Cannot |
| **Cross-workspace events** | ✅ Can publish and subscribe | ❌ Cannot (events stay in workspace) |

### Telegram = Global scope

Telegram connects to the Chief of Staff (global agent). Therefore:
- Telegram can do **everything** — manage any workspace, any task, any wiki
- The Chief of Staff routes requests to the correct workspace agent when appropriate
- When Kevin says "add a task to PhD", the CoS creates it in `PhD/tasks.yaml`
- When Kevin says "add a task to RiskStudio", the CoS creates it in `RiskStudio/tasks.yaml`

### Task management by agents

Agents can programmatically manage tasks within their scope:

```python
# Global agent: can modify any tasks.yaml
agent.add_task("PhD", name="review", schedule="0 10 * * *", message="Review papers")
agent.remove_task("PhD", "review")
agent.list_tasks("PhD")

# Workspace agent (PhD): can only modify PhD/tasks.yaml
agent.add_task(name="review", schedule="0 10 * * *", message="Review papers")
agent.remove_task("review")
agent.list_tasks()
```

### Wiki management by agents

Agents can read and write wiki pages within their scope:

```python
# Global agent: can read/write any wiki
agent.read_wiki("PhD", "Mechanistic Interpretability")
agent.write_wiki("RiskStudio", "New Architecture Doc", content)

# Workspace agent (PhD): can only read/write PhD wiki
agent.read_wiki("Mechanistic Interpretability")
agent.write_wiki("New Paper Summary", content)
```

### Self-modification rules

- **Agents cannot modify their own system_prompt** (prevents drift)
- **Agent Architect (global) can modify any agent's prompt** (human approves)
- **Workspace agents can propose new agents** for their workspace (human approves)
- **Agent Optimizer can suggest prompt changes** (human approves, Agent Architect implements)

## Consequences

- **Pro:** Clear boundaries. Workspace agents can't accidentally break other workspaces.
- **Pro:** Telegram (via Chief of Staff) has full control — Kevin is always in charge.
- **Pro:** Self-learning stays scoped — skills extracted in PhD don't pollute RiskStudio.
- **Con:** Cross-workspace intelligence requires going through the Chief of Staff (extra hop).
- **Con:** More complex agent code — each agent needs scope checking.
