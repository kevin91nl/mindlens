#!/bin/bash
# MindLens Installer
# Usage: ./install.sh

set -e

echo "🧠 MindLens Installer"
echo "====================="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Install Python 3.12+ first."
    exit 1
fi

# Check uv
if ! command -v uv &> /dev/null; then
    echo "📦 Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "✅ uv found: $(uv --version)"

# Install dependencies
echo ""
echo "📦 Installing dependencies..."
uv sync

# Setup .env
if [ ! -f .env ]; then
    echo ""
    echo "📝 Creating .env from template..."
    cp .env.example .env
    echo ""
    echo "⚠️  Edit .env with your API keys before running:"
    echo "   - OpenRouter API key (https://openrouter.ai/keys)"
    echo "   - Telegram bot token (https://t.me/BotFather)"
    echo "   - Your Telegram user ID (https://t.me/userinfobot)"
    echo "   - Vault path (your Obsidian vault)"
    echo ""
    echo "   nano .env"
fi

# Create example vault structure if vault path is set
if [ -n "$MINDLENS_VAULT_PATH" ] && [ -d "$MINDLENS_VAULT_PATH" ]; then
    echo ""
    echo "📁 Vault found at: $MINDLENS_VAULT_PATH"
else
    echo ""
    echo "📁 No vault configured yet. After editing .env, run:"
    echo "   uv run mindlens-cli init"
fi

echo ""
echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys"
echo "  2. Run: uv run mindlens-cli init"
echo "  3. Run: uv run mindlens-cli start"
echo ""
