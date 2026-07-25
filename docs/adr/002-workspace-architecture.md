# ADR-002: Workspace Architecture

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** Kevin

## Context

MindLens manages multiple autonomous workspaces. Each workspace is an independent "mini-company" with its own mission, knowledge, agents, and linked repos. Workspaces must be creatable and manageable via natural language through Telegram.

## Decision

### Workspace = Obsidian subfolder

Each workspace is a subfolder in the vault:

```
<WorkspaceName>/
├── raw/                        # Input zone (PDFs, URLs, notes, screenshots)
├── wiki/                       # Distilled knowledge (Obsidian pages with wikilinks)
├── .mindlens/
│   ├── skills/                 # Workspace-specific skills
│   ├── instructions/           # Workspace-specific instructions
│   └── workspace.db            # Workspace runtime state (events, tasks, agent runs)
├── repos.yaml                  # Linked code repos with paths
└── constitution.md             # Mission, priorities, forbidden actions, autonomy level
```

### Repo linking via repos.yaml

```yaml
repos:
  - name: riskstudio-worker
    path: ~/projects/riskstudio-worker
  - name: riskstudio-sdk
    path: ~/projects/riskstudio-sdk
```

A workspace owns 0..N repos. Repos live in `~/projects/` (not in the vault). The vault documents and links to them.

### Initial workspaces

- **PhD** — Research & knowledge distillation
- **Tuvia** — AI-driven business (content TBD)
- **RiskStudio** — Architecture documentation & quality tracking

### New workspaces via Telegram

```
Kevin: "Create workspace Marketing"
Chief of Staff: Creates folder, default constitution, asks for mission
```

## Consequences

- **Pro:** Adding a workspace = adding a folder with config files. No code changes needed.
- **Pro:** Obsidian shows all workspaces in one vault. Unified knowledge graph.
- **Pro:** Each workspace is independently configurable.
- **Con:** Workspace names must be valid folder names (no spaces, special chars).
