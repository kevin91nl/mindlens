# ADR-004: Skill & Learning System

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** Kevin

## Context

MindLens agents must get smarter over time. Skills, instructions, and patterns learned during tasks must be captured, stored, and made available to future agent runs. The system must be token-aware — agents shouldn't dump all skills into context, but selectively load what's relevant.

## Decision

### Skill storage: two levels

1. **Global skills** (`.mindlens/skills/`) — Available to all workspaces. General patterns like debugging, API design, error handling.
2. **Workspace skills** (`<Workspace>/.mindlens/skills/`) — Domain-specific. PhD has paper-analysis, RiskStudio has python-worker-patterns.

### Skill discovery: index-first loading

```yaml
# .mindlens/skills/index.yaml
- name: debugging-patterns
  description: Systematic debugging approach for Python async code
  path: debugging-patterns.md
  tokens: 450
  useful_count: 12
  last_used: 2026-07-25
```

Agents load the index at startup (~500 tokens). When a task matches a skill description, the agent loads the full content (~200-2000 tokens). Budget: max 5 skills per task.

### Skill format

Skills follow the OpenCode-compatible format:

```markdown
---
name: skill-name
description: One-line description of what this skill covers
applyTo: "*.py"  # Optional file pattern
---

# Skill content here
```

### Self-learning loop

After every task, the Agent Librarian runs post-task extraction:

1. Collect: task description, diff, test results, errors hit
2. Ask LLM: "Did we learn anything reusable? Pattern, pitfall, shortcut?"
3. If yes → create/update skill in appropriate `.mindlens/skills/`
4. Update `index.yaml` with new entry
5. Log the extraction in `workspace.db`

### Token tracking

Every agent run records in `core.db`:

```sql
CREATE TABLE agent_runs (
    id TEXT PRIMARY KEY,
    agent_name TEXT,
    workspace TEXT,
    task_description TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    skills_loaded TEXT,       -- JSON list of skill names
    skills_useful TEXT,       -- which skills actually helped
    duration_seconds REAL,
    success BOOLEAN,
    created_at TIMESTAMP
);
```

Agent Optimizer queries this to:
- Archive unused skills
- Rewrite ineffective skills
- Tighten skill selection to reduce tokens
- Track cost trends per workspace

### Instructions vs Skills

- **Instructions** = always loaded. Rules, standards, constraints. Small (~200-500 tokens each).
- **Skills** = loaded on demand. Patterns, procedures, domain knowledge. Variable size.

Both use the same OpenCode-compatible format.

## Consequences

- **Pro:** System gets measurably smarter over time.
- **Pro:** Token-aware loading keeps costs down.
- **Pro:** Skills are portable (same format as OpenCode, VS Code, etc.).
- **Con:** Post-task extraction adds latency and cost per task. Worth it for long-term savings.
- **Con:** Skill quality depends on LLM extraction. May need human curation for critical skills.
