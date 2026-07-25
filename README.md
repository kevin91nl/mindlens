# MindLens

<p align="center">
🧠 <strong>An operating system for understanding and orchestrating artificial minds</strong><br>
<em>AI-native workspaces • Self-improving agents • Natural language interface</em>
</p>

<p align="center">
<a href="https://pypi.org/project/mindlens/"><img src="https://img.shields.io/pypi/v/mindlens" alt="PyPI"></a>
<a href="https://github.com/kevin91nl/mindlens"><img src="https://img.shields.io/github/stars/kevin91nl/mindlens" alt="Stars"></a>
<a href="https://github.com/kevin91nl/mindlens/blob/main/LICENSE"><img src="https://img.shields.io/github/license/kevin91nl/mindlens" alt="License"></a>
</p>

---

## What is MindLens?

MindLens is an AI-native operating system for building, understanding, and orchestrating autonomous AI workspaces.

Think of it as a **holding company where AI agents are the employees**.

Each workspace has its own knowledge base, agent swarm, and code repos. You interact via **Telegram** using natural language.

## Why MindLens?

Most AI tools help you build a single chatbot or agent. MindLens helps you build an **entire organization of AI agents** — each with their own workspace, knowledge base, and tools.

Instead of one monolithic AI, you get a team:
- Agents that triage and fix issues autonomously
- Agents that monitor code quality and architecture
- Agents that research competitors and market gaps
- All coordinated through a single Telegram interface

Think of it as a **holding company where AI agents are the employees**.

## Architecture

```
You (Telegram)
    │
    ▼
MindLens Core
    │
    ├── 🔬 Research Lab
    │   ├── Paper discovery & synthesis
    │   ├── Hypothesis tracking
    │   ├── Literature review pipeline
    │   └── Experimental results
    │
    ├── 💼 Venture Studio
    │   ├── Market research
    │   ├── Product discovery
    │   └── Company creation
    │
    └── 🔧 Custom Workspace
        ├── Your agents
        └── Your pipelines
```

## Quick Start

```bash
pip install mindlens
```

MindLens auto-discovers your vault. Put `.env` in your vault:

```bash
# Your vault (auto-discovered via Proton Drive, iCloud, or ~/mindlens)
cd ~/mindlens-vault
cp .env.example .env
nano .env
```

```bash
# Run
mindlens
```

You need:
- **OpenRouter API key** — https://openrouter.ai/keys
- **Telegram bot token** — @BotFather
- **Your Telegram user ID** — @userinfobot

## License

MIT
