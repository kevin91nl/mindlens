# ADR-006: OpenCode Integration

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** Kevin

## Context

MindLens agents need code development capabilities. The coding backend must work with OpenRouter models (MiMo V2.5 Pro), be scriptable, and integrate with the skill/instruction system.

## Decision

### OpenCode as coding backend

Use OpenCode-compatible tooling for code agents. OpenCode provides:
- Multi-file edits with git awareness
- Terminal access for running tests, builds
- Skill and instruction loading from `.instructions.md`, `SKILL.md`, `AGENTS.md`
- Model-agnostic (works with OpenRouter)

### Skill format compatibility

MindLens uses the **same skill/instruction file format** as OpenCode:
- `SKILL.md` with YAML frontmatter (`name`, `description`, `applyTo`)
- `.instructions.md` for coding rules
- `AGENTS.md` for agent behavior guidelines

This means:
- Skills created in MindLens work in OpenCode sessions
- Skills learned in OpenCode sessions are available to MindLens agents
- No duplication, one source of truth

### Agent ↔ Vault access

Code agents get:

| Access | Level |
|--------|-------|
| Global skills/index | Always loaded |
| Workspace skills | Always loaded |
| Workspace constitution | Always loaded |
| Workspace wiki | Read + search on demand |
| Workspace raw | Read on demand |
| Code repos | Full read/write + git |
| Wiki writes | Propose only (human approves) |

### Vault path resolution

```bash
# .env
MINDLENS_VAULT_PATH=/Users/kevin/Library/CloudStorage/ProtonDrive-kevjac91@proton.me-folder/mindlens
```

Agent config references `${MINDLENS_VAULT_PATH}` for all vault paths.

### OpenCode runs IN repos, reads FROM vault

When OpenCode runs in `~/projects/riskstudio-worker/`:
- It reads skills from `mindlens/RiskStudio/.mindlens/skills/`
- It reads instructions from `mindlens/.mindlens/instructions/`
- It reads wiki from `mindlens/RiskStudio/wiki/`
- It writes code to `~/projects/riskstudio-worker/`

When MindLens runs agents via Telegram:
- They read the SAME skills and instructions
- Same knowledge, same learning

## Consequences

- **Pro:** Code agents have institutional knowledge (vault/wiki access).
- **Pro:** Skills are portable between manual OpenCode sessions and automated MindLens runs.
- **Pro:** No vendor lock-in. Skill format is open and widely compatible.
- **Con:** Need to configure OpenCode to read skills from vault paths. May require symlinks or config.
