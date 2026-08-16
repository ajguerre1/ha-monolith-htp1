"""Shared facts about the layout, importable by name without colliding.

This exists because `tests/conftest.py` and `tests/ha/conftest.py` both resolve as the
top-level module `conftest` under pytest's rootdir collection. A test that did
`from conftest import ...` therefore got whichever one was imported first — which is the root
conftest locally, where `tests/ha` is skipped entirely, and the *wrong* one in CI, where it is
not.

The symptom was an ImportError that could not happen on the development machine. Anything two
test modules both need lives here instead.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "ha_monolith_htp1"
INTEGRATION_DIR = REPO_ROOT / "custom_components" / DOMAIN
CLIENT_DIR = INTEGRATION_DIR / "htp1"


def home_assistant_available() -> bool:
    """Whether Home Assistant can be imported at all.

    False on the Windows development box — `homeassistant.runner` imports POSIX-only `fcntl` —
    and True in CI. Everything about the split test layout follows from this one fact.
    """
    try:
        import homeassistant  # noqa: F401
    except ImportError:
        return False
    return True
