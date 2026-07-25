"""Agent discovery utilities — finds YAML agent definitions in the vault.

Two-layer discovery:
  1. Built-in agents (shipped with pip install mindlens)
  2. User agents in vault (override built-in if same name)
"""

from __future__ import annotations

from pathlib import Path


def _builtin_agents_dir() -> Path:
    """Return the built-in agents directory shipped with the package."""
    return Path(__file__).parent / "builtin"


def discover_yaml_agents(vault_path: Path) -> list[Path]:
    """Discover all YAML agent definitions using two-layer resolution.

    Layer 1 — built-in agents (``agents/builtin/*.yaml`` inside the package).
    Layer 2 — user agents in ``<vault>/agents/*.yaml`` (override by name).
    Layer 3 — workspace agents in ``<vault>/<workspace>/agents/*.yaml``.
    """
    agents: dict[str, Path] = {}

    # Layer 1: built-in agents (shipped with the package)
    builtin_dir = _builtin_agents_dir()
    if builtin_dir.is_dir():
        for p in sorted(builtin_dir.glob("*.yaml")):
            agents[p.stem] = p

    # Layer 2: global user agents (override built-in if same name)
    global_dir = vault_path / "agents"
    if global_dir.is_dir():
        for p in sorted(global_dir.glob("*.yaml")):
            agents[p.stem] = p  # overrides built-in

    result = list(agents.values())

    # Layer 3: workspace agents (always additive, never override global)
    for item in sorted(vault_path.iterdir()):
        if item.is_dir() and not item.name.startswith((".", "_")):
            ws_agents = item / "agents"
            if ws_agents.is_dir():
                result.extend(sorted(ws_agents.glob("*.yaml")))

    return result
