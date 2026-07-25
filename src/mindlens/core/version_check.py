"""Version check — compare installed version against PyPI on startup.

Respects dev mode: never auto-updates editable installs.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

PYPI_URL = "https://pypi.org/pypi/mindlens/json"
REQUEST_TIMEOUT = 5.0


def get_installed_version() -> str:
    """Return the currently installed version of mindlens."""
    try:
        return distribution("mindlens").version
    except PackageNotFoundError:
        return "0.0.0"


def is_editable_install() -> bool:
    """Detect if mindlens is installed in editable/dev mode.

    Checks direct_url.json (PEP 610) for editable flag,
    then falls back to checking if .git exists near the package.
    """
    try:
        dist = distribution("mindlens")
        direct_url = dist.read_text("direct_url.json")
        if direct_url:
            info = json.loads(direct_url)
            if info.get("dir_info", {}).get("editable"):
                return True
            # Source install (not from PyPI)
            if info.get("url", "").startswith("file://"):
                return True
    except Exception:
        pass

    # Fallback: check if running from a git checkout
    try:
        import mindlens
        pkg_path = Path(mindlens.__file__).resolve().parent
        # Walk up looking for .git
        for parent in [pkg_path, *pkg_path.parents]:
            if (parent / ".git").exists():
                return True
    except Exception:
        pass

    return False


def fetch_latest_version() -> str | None:
    """Query PyPI for the latest mindlens version. Returns None on failure."""
    try:
        resp = httpx.get(PYPI_URL, timeout=REQUEST_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return resp.json()["info"]["version"]
    except Exception as exc:
        logger.debug("PyPI version check failed: %s", exc)
        return None


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse 'x.y.z' into comparable tuple."""
    try:
        return tuple(int(p) for p in v.split("."))
    except (ValueError, AttributeError):
        return (0,)


def upgrade_package() -> bool:
    """Run pip install --upgrade mindlens. Returns True on success."""
    logger.info("⬆️  Upgrading mindlens via pip...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "mindlens"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info("✅ mindlens upgraded successfully. Restart to use new version.")
            return True
        else:
            logger.warning("⚠️  Upgrade failed:\n%s", result.stderr[-500:] if result.stderr else result.stdout[-500:])
            return False
    except subprocess.TimeoutExpired:
        logger.warning("⚠️  Upgrade timed out after 120s")
        return False
    except Exception as exc:
        logger.warning("⚠️  Upgrade error: %s", exc)
        return False


def check_and_update(*, auto_update: bool = False) -> str | None:
    """Check for updates on startup. Returns latest version if available, else None.

    Args:
        auto_update: If True, automatically downloads + installs newer version.
                     Ignored for editable installs (always safe).

    Returns:
        Latest version string if an update is available, None otherwise.
    """
    current = get_installed_version()
    editable = is_editable_install()

    if editable:
        logger.info("🔧 Dev mode detected (editable install) — skipping auto-update")
        latest = fetch_latest_version()
        if latest and _parse_version(latest) > _parse_version(current):
            logger.info(
                "📦 Update available: %s → %s (run `pip install --upgrade mindlens` to update)",
                current,
                latest,
            )
            return latest
        logger.info("✅ mindlens %s (dev, up to date)", current)
        return None

    # Non-editable install
    latest = fetch_latest_version()
    if not latest:
        logger.info("✅ mindlens %s (could not check PyPI)", current)
        return None

    if _parse_version(latest) <= _parse_version(current):
        logger.info("✅ mindlens %s (up to date)", current)
        return None

    # Update available
    logger.info("📦 New version available: %s → %s", current, latest)

    if auto_update:
        if upgrade_package():
            return latest
        # Upgrade failed — continue with current version
        return latest

    logger.info("   Run `pip install --upgrade mindlens` to update.")
    return latest
