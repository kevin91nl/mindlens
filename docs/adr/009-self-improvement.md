# ADR-009: Self-Improvement System (Cortex)

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** Kevin

## Context

MindLens needs a system that continuously observes, measures, and improves itself. Token efficiency, agent quality, skill relevance, and overall system health should improve over time — measurably.

## Decision

### Cortex — Global self-improvement workspace

A dedicated workspace called **Cortex** with `scope: global` flag. It can read everything across all workspaces but never modifies workspace-specific content directly.

### Agents

| Agent | Role | Reads | Writes |
|-------|------|-------|--------|
| **Session Observer** | Reads VS Code chat transcripts, identifies waste, errors, repeated patterns | All transcripts | Cortex wiki, improvement proposals |
| **Efficiency Analyst** | Queries agent_runs DB, tracks token/cost trends, identifies expensive operations | core.db, all task configs | Cortex wiki, efficiency reports |
| **Reflector** | Periodic deep reflection on system health, generates actionable improvements | All Cortex data | Improvement proposals, skill suggestions |
| **Memory Manager** | Extracts lessons from completed tasks, manages skill lifecycle | All task results, skill indexes | Global skill index, skill files |
| **Test Runner** | Verifies improvements actually work, runs regression tests | Cortex proposals | Test results, approval/rejection |

### What Cortex observes

1. **Token usage per agent per workspace** — trends over time
2. **Chat session patterns** — what questions fail, what's slow, what's repeated
3. **Skill effectiveness** — which skills are loaded but never useful
4. **Pipeline performance** — how long does raw→wiki take, where are bottlenecks
5. **Scheduled task efficiency** — are tasks worth running? Do they produce value?
6. **Agent routing accuracy** — does the CoS route correctly?
7. **Wasted time** — idle periods, slow responses, unnecessary LLM calls

### What Cortex produces

1. **Efficiency reports** — token/cost trends, waste identification
2. **Improvement proposals** — concrete suggestions with expected impact
3. **Skill recommendations** — new skills to extract, old skills to archive
4. **Test results** — verification that improvements work
5. **Memory reflections** — what the system learned, what patterns emerged

### Notification rules

- **Daily efficiency report** — always sent to Telegram (notify: full)
- **Improvement proposals** — always sent (notify: full)
- **Skill extraction** — summary notification (notify: summary)
- **Test results** — only if failures (notify: summary)
- **Reflections** — weekly digest (notify: full)

### Self-improvement loop

```
1. Observe (Session Observer, Efficiency Analyst)
   ↓
2. Analyze (Reflector)
   ↓
3. Propose (Reflector → improvement proposal)
   ↓
4. Test (Test Runner → verify proposal works)
   ↓
5. Apply (Memory Manager → update skills/config)
   ↓
6. Measure (Efficiency Analyst → did it improve?)
   ↓
7. Repeat
```

### What Cortex NEVER does

- ❌ Modify workspace-specific files (wiki, tasks, issues, agents)
- ❌ Run code in workspace repos
- ❌ Make architectural decisions (proposes, Kevin approves)
- ❌ Auto-apply improvements without testing

## Consequences

- **Pro:** Measurable self-improvement over time
- **Pro:** Waste identification leads to cost savings
- **Pro:** Lessons extracted from every task
- **Pro:** System gets smarter with each interaction
- **Con:** Additional token cost for observation/analysis
- **Con:** Risk of "improvement theater" — changes that don't actually help
