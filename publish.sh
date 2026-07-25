#!/bin/bash
# Publish mindlens to PyPI
# Usage: ./publish.sh [test|prod]

set -e

ENV=${1:-test}

if [ "$ENV" = "test" ]; then
    echo "📤 Publishing to TestPyPI..."
    uv run python -m build
    uv run twine upload --repository testpypi dist/*
    echo "✅ Published to https://test.pypi.org/project/mindlens/"
    echo "Install: pip install --index-url https://test.pypi.org/simple/ mindlens"
else
    echo "📤 Publishing to PyPI..."
    uv run python -m build
    uv run twine upload dist/*
    echo "✅ Published to https://pypi.org/project/mindlens/"
    echo "Install: pip install mindlens"
fi
