# MindLens — AI-Native Holding Company OS

<p align="center">
🧠 <strong>An operating system for autonomous AI workspaces</strong><br>
<em>Natural language interface via Telegram • Self-improving • Multi-workspace</em>
</p>

<p align="center">
<a href="https://pypi.org/project/mindlens/"><img src="https://img.shields.io/pypi/v/mindlens" alt="PyPI"></a>
<a href="https://github.com/kevin91nl/mindlens"><img src="https://img.shields.io/github/stars/kevin91nl/mindlens" alt="Stars"></a>
<a href="https://github.com/kevin91nl/mindlens/blob/main/LICENSE"><img src="https://img.shields.io/github/license/kevin91nl/mindlens" alt="License"></a>
</p>

---

## What is MindLens?

MindLens manages **autonomous workspaces** — each with its own knowledge base, agent swarm, and code repos. You interact via **Telegram** using natural language.

Think of it as a **holding company** where AI agents are the employees.

```
You (Telegram)
    │
    ▼
MindLens Core
    │
    ├── 📚 PhD Workspace
    │   ├── Raw → Wiki pipeline (LangGraph)
    │   ├── Hypothesis tracking
    │   └── Paper processing
    │
    ├── 💼 Business Workspace
    │   ├── Market research
    │   └── Opportunity analysis
    │
    └── 🔧 Custom Workspace
        ├── Your agents
        └── Your pipelines
```

## Quick Start

### 1. Install

```bash
# Install from PyPI
pip install mindlens

# Or with uv (recommended)
uv pip install mindlens
```

### 2. Configure

```bash
# Create your vault
mkdir -p ~/mindlens-vault

# Copy the example config
cp .env.example .env

# Edit with your values
nano .env
```

You need:
- **OpenRouter API key** — Get one at https://openrouter.ai/keys
- **Telegram bot token** — Create via [@BotFather](https://t.me/BotFather)
- **Your Telegram user ID** — Get via [@userinfobot](https://t.me/userinfobot)
- **Vault path** — Where your Obsidian vault lives

### 3. Run

```bash
# Start MindLens
mindlens

# Or via uv
uv run mindlens
```

### 4. Use

Open Telegram, message your bot:

```
Hi                           → Greeting (streams response)
What is the status?          → System status
Create workspace Marketing   → New workspace
Add a task to PhD            → Task management
Show my VS Code sessions     → Session overview
```

## Architecture

### Dual-location design

```
Your Obsidian Vault (local/cloud)     ~/projects/mindlens/ (git repo)
├── agents/                           ├── src/mindlens/
│   └── *.yaml                        │   ├── core/
├── tasks.yaml                        │   ├── agents/
├── issues.yaml                       │   ├── pipelines/
├── docs/adr/                         │   └── workspaces/
├── Workspace1/                       ├── tests/
│   ├── agents/                       ├── pyproject.toml
│   ├── tasks.yaml                    └── install.sh
│   ├── issues.yaml
│   └── wiki/
└── Workspace2/
    └── ...
```

- **Vault** = knowledge, config, decisions (your Obsidian)
- **Code** = Python runtime (this repo)

### Key concepts

| Concept | What | Where |
|---------|------|-------|
| **Workspaces** | Autonomous organizational units | Vault subfolders |
| **Agents** | AI workers with specific roles | `agents/*.yaml` + Python |
| **Skills** | Reusable knowledge patterns | `.mindlens/skills/` |
| **Tasks** | Scheduled recurring work | `tasks.yaml` per level |
| **Issues** | Kanban board for tracking | `issues.yaml` per level |
| **ADRs** | Architectural decisions | `docs/adr/` |

### Scope rules

- **Global agents** can modify everything
- **Workspace agents** can only modify their own workspace
- **Telegram** = global scope (you control everything)

## CLI Commands

```bash
# Start MindLens
mindlens-cli start

# Create a workspace
mindlens-cli workspace create MyProject

# List issues
mindlens-cli issues list --workspace PhD

# Add a task
mindlens-cli task add --workspace PhD --name "review-papers" --schedule "0 10 * * 1,3,5"

# View status
mindlens-cli status
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | Show available actions |
| `/status` | System status |
| `/workspace` | Switch workspace context |
| Natural language | Anything — routed to the right agent |

## Extending MindLens

### Add a new workspace

```bash
mindlens-cli workspace create MyProject
```

Or manually: create a folder in your vault with `constitution.md`, `tasks.yaml`, `issues.yaml`, and an `agents/` folder.

### Add a new agent

Create `agents/my_agent.yaml`:

```yaml
name: my_agent
description: What this agent does
type: knowledge
capabilities:
  - analyze
  - report
system_prompt: |
  You are a specialized agent for...
```

### Add a scheduled task

Edit `tasks.yaml`:

```yaml
tasks:
  - name: daily_review
    schedule: "0 9 * * *"
    agent: chief_of_staff
    workspace: MyProject
    message: "Review what happened yesterday"
    enabled: true
    notify: summary
```

## Tech Stack

- **Python 3.12+** with `uv`
- **LangGraph** for agent pipelines
- **python-telegram-bot** for Telegram
- **SQLite** for runtime state
- **OpenRouter API** for LLM access
- **Obsidian** as knowledge interface

## Contributing

1. Fork the repo
2. Create a feature branch
3. Make your changes
4. Submit a PR

## License

MIT
