# ADR-001: Self-Contained Architecture

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** Kevin

## Context

MindLens is an AI-native operating system for understanding and orchestrating artificial minds. It manages multiple autonomous workspaces (PhD, Tuvia, RiskStudio), each with their own knowledge base, agent swarms, and code repos. The system must be self-contained — all configuration, skills, instructions, and knowledge live inside the vault.

## Decision

MindLens follows a **dual-location architecture**:

1. **Vault** (Obsidian, Proton Drive Sync): All knowledge, configuration, skills, instructions, ADRs, constitutions. This is the "brain."
2. **Runtime** (`~/projects/mindlens/`): Python source code, git repo, `.venv/`, tests. This is the "engine."

### Why split?

- **Proton Drive + git = corruption risk**. Git internals (`.git/`) and cloud file sync conflict.
- **Python `.venv/`** contains thousands of files. Syncing them is wasteful and slow.
- **SQLite WAL/journal files** would be corrupted by cloud sync.

### What lives where

```
mindlens/ (vault, Proton Drive)
├── .env                            # Secrets (gitignored)
├── .obsidian/                      # Obsidian config
├── .mindlens/                      # Global runtime config
│   ├── skills/                     # Global skills (all workspaces)
│   ├── instructions/               # Global instructions
│   └── agents/                     # Agent definitions (YAML)
├── ADRs/                           # Architecture Decision Records
├── AGENTS.md                       # AI coding assistant guidelines
├── README.md                       # Project vision & setup
├── PhD/                            # Workspace
│   ├── raw/                        # Input zone
│   ├── wiki/                       # Knowledge output
│   ├── .mindlens/                  # Workspace skills, instructions
│   ├── repos.yaml                  # Linked repos
│   └── constitution.md             # Mission, rules, policies
├── Tuvia/
└── RiskStudio/

~/projects/mindlens/ (code, local git)
├── src/mindlens/                   # Python package
├── tests/
├── pyproject.toml
└── .venv/
```

### Connection point

The `.env` file contains `MINDLENS_VAULT_PATH` pointing to the vault. All code resolves paths relative to this. Agents read skills, instructions, and wiki content from the vault. Code agents write to repos at `~/projects/`.

## Consequences

- **Pro:** Clean separation. No sync corruption. No git conflicts.
- **Pro:** Vault stays pure knowledge. No code artifacts polluting Obsidian.
- **Pro:** Code repo can have CI, linting, tests without vault interference.
- **Con:** Two locations to manage. Mitigated by `MINDLENS_VAULT_PATH` config.
- **Con:** Agents need to bridge both locations. Mitigated by `repos.yaml` mapping.

## Related

- ADR-002: Workspace Architecture (pending)
- ADR-003: Agent System (pending)
- ADR-004: Skill & Learning System (pending)
