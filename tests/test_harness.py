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

import importlib
import sys

import pytest

# `tests/` deliberately has no __init__.py, so pytest collects with the directory on sys.path
# and conftest is a top-level module here rather than a relative import.
from conftest import DOMAIN, HA_AVAILABLE

PACKAGE = f"custom_components.{DOMAIN}"


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
