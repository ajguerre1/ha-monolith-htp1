"""Test configuration shared by the offline suite.

The suite is split deliberately. `tests/` imports no Home Assistant and runs anywhere,
including the Windows dev box. `tests/ha/` needs `pytest-homeassistant-custom-component`, which
pulls in Home Assistant, which cannot be imported on Windows at all — `homeassistant.runner`
imports the POSIX-only `fcntl`. Those tests run in CI.

Importing `custom_components.ha_monolith_htp1.htp1.protocol` would normally execute the
integration package's `__init__.py` on the way down, and from M2 onward that file imports Home
Assistant. Stubbing the two parent packages with the right `__path__` lets the vendored client
be imported without running it, which is what keeps the client genuinely testable in isolation
rather than only nominally so.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from support import DOMAIN, REPO_ROOT, home_assistant_available

FIXTURE_DIR = Path(__file__).parent / "fixtures"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

HA_AVAILABLE = home_assistant_available()

if not HA_AVAILABLE:
    for name, path in (
        ("custom_components", REPO_ROOT / "custom_components"),
        (f"custom_components.{DOMAIN}", REPO_ROOT / "custom_components" / DOMAIN),
    ):
        if name not in sys.modules:
            stub = types.ModuleType(name)
            stub.__path__ = [str(path)]
            sys.modules[name] = stub

    # Nothing under tests/ha can even be collected without Home Assistant.
    collect_ignore = ["ha"]
    collect_ignore_glob = ["ha/*"]


def load_fixture(name: str) -> dict:
    """Read a JSON fixture by bare name, e.g. `load_fixture("mso_modern")`."""
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def mso_modern() -> dict:
    """A firmware 2.x document: videostat present, one Dirac slot named ""."""
    return load_fixture("mso_modern")


@pytest.fixture(scope="session")
def mso_legacy() -> dict:
    """A firmware 1.x document: no videostat, one Dirac slot with no `name` key at all."""
    return load_fixture("mso_legacy")


@pytest.fixture(scope="session")
def mso_sparse() -> dict:
    """Two keys and nothing else. Absence tolerance, total."""
    return load_fixture("mso_sparse")


@pytest.fixture(scope="session")
def wire_samples() -> dict:
    """The message-level corpus: every shape the unit is known or believed to emit."""
    return load_fixture("wire_samples")
