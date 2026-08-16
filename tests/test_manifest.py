"""The packaging contract that HACS and hassfest enforce.

These are cheap file reads with no Home Assistant import, so they run on the Windows dev box
as well as in CI. They exist because the integration this one replaces shipped for a year
without `issue_tracker` and without a `custom_components/` wrapper, and the only symptom was
that HACS silently refused to install it.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "ha_monolith_htp1"
INTEGRATION_DIR = REPO_ROOT / "custom_components" / DOMAIN


def _manifest() -> dict:
    return json.loads((INTEGRATION_DIR / "manifest.json").read_text(encoding="utf-8"))


def test_integration_lives_under_custom_components() -> None:
    """HACS requires exactly this layout; a bare package at the repo root is not installable."""
    assert INTEGRATION_DIR.is_dir()
    assert (INTEGRATION_DIR / "manifest.json").is_file()
    assert (INTEGRATION_DIR / "__init__.py").is_file()


def test_manifest_carries_every_key_hacs_requires() -> None:
    manifest = _manifest()
    for key in ("domain", "documentation", "issue_tracker", "codeowners", "name", "version"):
        assert manifest.get(key), f"manifest.json is missing the HACS-required key {key!r}"


def test_domain_matches_the_package_directory() -> None:
    """A mismatch here loads as a different integration and orphans every entity."""
    assert _manifest()["domain"] == DOMAIN


def test_iot_class_is_local_push() -> None:
    """The unit pushes msoupdate on every change and an idle socket sent zero bytes over 90 s.

    Polling this device is pure waste, and `local_polling` would advertise a lie. The sibling
    ha_somfy integration is local_polling for good reasons of its own -- do not copy it here.
    """
    assert _manifest()["iot_class"] == "local_push"


def test_no_runtime_dependencies() -> None:
    """The client is vendored under htp1/ so manifest.json can keep requirements empty.

    A git+https requirement would be refetched on every restart, because Home Assistant's
    is_installed() returns False for URL requirements.
    """
    assert _manifest()["requirements"] == []


def test_hacs_json_is_present_and_names_a_minimum_ha_version() -> None:
    hacs = json.loads((REPO_ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs.get("name")
    # The integration uses entry.runtime_data and AddConfigEntryEntitiesCallback.
    assert hacs.get("homeassistant")
