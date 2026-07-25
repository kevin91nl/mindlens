# ADR-008: Inter-Agent Communication & Scope Control

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** Kevin

## Context

Agents need to communicate with each other, manage resources within their scope, and escalate when needed. Clear rules are needed for who can talk to whom and what each agent can control.

## Decision

### Communication rules

1. **Agents within the same scope can always communicate with each other.**
   - PhD agents can talk to other PhD agents freely.
   - Global agents can talk to other global agents freely.

2. **Global agents can communicate with workspace agents (top-down).**
   - Chief of Staff can send tasks to PhD's HypothesisEvidenceTracker.
   - Agent Architect can modify workspace agent configs.

3. **Workspace agents CANNOT communicate with global agents (bottom-up).**
   - PhD agents cannot send messages to the Chief of Staff directly.
   - If a workspace agent needs global attention, it publishes an event. The Chief of Staff subscribes to all events and can act on them.

4. **Workspace agents CANNOT communicate with other workspace agents (cross-workspace).**
   - PhD agents cannot talk to RiskStudio agents.
   - Cross-workspace communication goes through the Chief of Staff (global).

### Scope control — maximum autonomy

Each agent has **maximum control** over everything within its scope:

| Resource | Global agents | Workspace agents |
|----------|--------------|-----------------|
| **Issues** | All `issues.yaml` in all workspaces + root | Only own `issues.yaml` |
| **Tasks** | All `tasks.yaml` everywhere | Only own `tasks.yaml` |
| **Wiki** | All wiki pages everywhere | Only own wiki pages |
| **Agents** | All agent definitions everywhere | Only own workspace agents |
| **Constitutions** | All constitutions | Only own constitution |
| **Repos** | All repos | Only own repos |
| **Scheduled tasks** | All scheduled tasks | Only own scheduled tasks |
| **Skills** | All skills everywhere | Only own skills |

### Issue lifecycle

```
backlog → todo → in_progress → review → done
                                        ↗
                              blocked ──┘
```

- **backlog**: Not yet planned for work
- **todo**: Ready to be worked on
- **in_progress**: Agent is actively working on it
- **review**: Work done, needs independent verification
- **done**: Verified and complete
- **blocked**: Waiting on dependency

### Large task grilling

When a task or issue is too large (detected by the agent or flagged by Kevin):
1. Chief of Staff asks Kevin via Telegram: "This task seems large. How would you like to split it?"
2. Kevin suggests subtasks
3. Chief of Staff creates sub-issues in `issues.yaml`
4. Original issue becomes an epic (parent) tracking sub-issues

### Independent reviewer

A **Reviewer Agent** (workspace-scoped) evaluates whether issues in `review` status are actually done:
- Checks code changes (if applicable)
- Verifies wiki pages are complete
- Tests functionality
- Approves → moves to `done`
- Rejects → moves back to `in_progress` with feedback

## Consequences

- **Pro:** Clear communication hierarchy. No chaos.
- **Pro:** Agents have full autonomy within their scope.
- **Pro:** Issues provide visibility into what agents are doing.
- **Pro:** Grilling prevents agents from doing too much at once.
- **Pro:** Independent review ensures quality.
- **Con:** Workspace agents can't escalate directly to global (must use events).
- **Con:** More YAML files to manage per workspace.
