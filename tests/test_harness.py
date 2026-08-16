"""The test harness itself, which the whole offline workflow depends on.

`tests/` is supposed to run on a machine where Home Assistant cannot be imported at all — on
Windows `homeassistant.runner` imports the POSIX-only `fcntl`. That only holds if importing
something out of `custom_components.ha_monolith_htp1.htp1` does not execute the integration
package's `__init__.py` on the way down, because from M2 onward that file imports Home
Assistant.

If these tests fail, the symptom elsewhere is every client test erroring at import time on a
machine that was supposed to be able to run them.
"""

from __future__ import annotations

import ast
import importlib
import sys

import pytest

# Imported from support rather than conftest: `tests/ha/conftest.py` resolves under the same
# top-level name, so `from conftest import ...` picks up whichever was imported first.
from support import CLIENT_DIR, DOMAIN, home_assistant_available

HA_AVAILABLE = home_assistant_available()
PACKAGE = f"custom_components.{DOMAIN}"


def _home_assistant_imports(source: str) -> list[str]:
    """Return every `homeassistant` import in `source`, by AST rather than by grepping.

    A substring search would be fooled by the word appearing in a docstring — which it does,
    repeatedly, in this very package.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(a.name for a in node.names if a.name.split(".")[0] == "homeassistant")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root == "homeassistant":
                found.append(node.module or "")
    return found


def test_the_vendored_package_is_importable_without_home_assistant():
    """The property that makes the client testable in isolation rather than only nominally."""
    module = importlib.import_module(f"{PACKAGE}.const")
    assert module.DOMAIN == DOMAIN


def test_the_parent_packages_are_stubbed_when_home_assistant_is_absent():
    """A stub has no __file__, because it was never loaded from disk and never executed.

    This is the whole trick: the real `__init__.py` is bypassed, not merely tolerated.
    """
    if HA_AVAILABLE:
        pytest.skip("Home Assistant is installed, so the real packages load normally")

    for name in ("custom_components", PACKAGE):
        assert name in sys.modules, f"{name} should have been stubbed during collection"
        assert getattr(sys.modules[name], "__file__", None) is None, (
            f"{name} was loaded from disk rather than stubbed, so its __init__.py ran"
        )
        assert sys.modules[name].__path__, f"{name} needs a __path__ for submodules to resolve"


def test_the_home_assistant_import_detector_actually_detects():
    """A guard that cannot fail is not a guard. Prove the detector before trusting it."""
    assert _home_assistant_imports("import homeassistant") == ["homeassistant"]
    assert _home_assistant_imports("from homeassistant.core import HomeAssistant") == [
        "homeassistant.core"
    ]
    assert _home_assistant_imports("import homeassistant.helpers.entity as e") == [
        "homeassistant.helpers.entity"
    ]
    # The word appears in prose all over this package; only real imports count.
    assert _home_assistant_imports('"""Mentions homeassistant in a docstring."""') == []
    assert _home_assistant_imports("import aiohttp\nfrom json import loads") == []


def test_the_client_package_imports_no_home_assistant():
    """AC-19. This is the property that keeps the whole client testable off a Home Assistant box.

    It is also the property that lets `manifest.json` stay `requirements: []`, since the client
    is vendored rather than depended upon.
    """
    offenders: dict[str, list[str]] = {}
    sources = sorted(CLIENT_DIR.glob("*.py"))
    assert sources, f"no modules found under {CLIENT_DIR}; the glob is probably wrong"

    for path in sources:
        imports = _home_assistant_imports(path.read_text(encoding="utf-8"))
        if imports:
            offenders[path.name] = imports

    assert not offenders, f"the vendored client must not import Home Assistant: {offenders}"
