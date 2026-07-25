# ADR-005: Telegram Interface

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** Kevin

## Context

MindLens needs a user interface. Kevin communicates via Telegram. The ChatGPT vision proposed 4 separate chats (HQ, PhD, Tuvia, Alerts), but managing 5 groups is cumbersome for daily use.

## Decision

### One bot, one DM, workspace-aware routing

Single Telegram bot, single direct message conversation. The bot maintains workspace context state:

```
Kevin: "Summarize the latest papers"
Bot: [currently in PhD context] → runs PhD knowledge pipeline

Kevin: "Switch to RiskStudio"
Bot: "Switched to RiskStudio. What do you need?"

Kevin: "Fix the retry logic"
Bot: [currently in RiskStudio context] → spawns code agent in riskstudio-worker
```

### Bot always shows context

```
[PhD] > summarize latest papers
[RiskStudio] > fix retry logic
[HQ] > daily briefing
```

### Natural language primary

No slash commands. Pure natural language. The Chief of Staff interprets intent and routes.

Examples:
- "Create a new workspace called Marketing" → Workspace Manager
- "Add a citation checker to PhD" → Agent Architect
- "How is my system performing?" → Agent Optimizer
- "What did we learn this week?" → Agent Librarian

### User ID gating

Only Telegram user ID `6537484311` can interact. All others rejected.

## Consequences

- **Pro:** Simple UX. One chat, no context switching between groups.
- **Pro:** Natural language is intuitive.
- **Con:** Context state must be tracked. If bot restarts, needs to remember last workspace.
- **Con:** Ambiguous commands might go to wrong workspace. Bot should confirm if unsure.
