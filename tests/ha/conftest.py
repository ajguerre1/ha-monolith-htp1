"""Fixtures for the Home Assistant-dependent tests.

Everything in this directory needs `pytest-homeassistant-custom-component`, which pulls in Home
Assistant, which cannot be imported on Windows — `homeassistant.runner` imports POSIX-only
`fcntl`. The root conftest sets `collect_ignore` so this directory is skipped there entirely.
These run in CI, and CI is the authority for them.

The device is faked at the **client object** boundary rather than at the socket. The client's
own behaviour has its own suite, over a real socket, in `tests/test_integration_fake_device.py`;
what these tests are about is the Home Assistant layer around it.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_monolith_htp1.const import DOMAIN
from custom_components.ha_monolith_htp1.htp1.mso import TRACKED_PATHS, MsoMirror

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Without this, Home Assistant refuses to load anything from custom_components."""
    yield


@pytest.fixture
def document() -> dict:
    return json.loads((FIXTURES / "mso_modern.json").read_text(encoding="utf-8"))


@pytest.fixture
def mirror(document) -> MsoMirror:
    loaded = MsoMirror()
    loaded.apply_document(document)
    return loaded


@pytest.fixture
def mso_legacy_mirror() -> MsoMirror:
    """A firmware 1.13.x document: no video block at all."""
    loaded = MsoMirror()
    loaded.apply_document(json.loads((FIXTURES / "mso_legacy.json").read_text(encoding="utf-8")))
    return loaded


@pytest.fixture
def mock_client(mirror) -> MagicMock:
    """A stand-in for `Htp1Client` with every method the integration calls.

    `add_listener` records the callback and returns a real unsubscribe, so a test can drive a
    push by calling the recorded callback — which is exactly how the client drives it.
    """
    client = MagicMock()
    client.host = "10.0.0.1"
    client.connected = True
    client.reconnecting = True
    client.mirror = mirror
    client.pending_paths = ()

    def optimistic(path: str):
        """Wire path to mirrored value, the way the real client does it.

        Not `mirror.get(path.strip("/"))`: the mirror is keyed by *field name*, so `/powerIsOn`
        is `power` and `/upmix/select` is `upmix`. Stripping slashes returns None for every
        path whose name differs from its last segment, which is most of them.
        """
        field = TRACKED_PATHS.get(path)
        return mirror.get(field.name) if field else None

    client.optimistic.side_effect = optimistic

    client.async_start = AsyncMock()
    client.async_stop = AsyncMock()
    client.async_refresh = AsyncMock()
    client.async_write = AsyncMock()
    # Explicit rather than left to MagicMock's auto-attribute: an auto-created child is not
    # awaitable, so a coordinator that started using it would fail for the wrong reason.
    client.async_write_many = AsyncMock()

    listeners: list = []
    client.listeners = listeners

    def add_listener(callback):
        listeners.append(callback)

        def unsubscribe():
            # Tolerant, because the real client's is: `test_unsubscribing_twice_is_harmless`
            # pins that. A stricter mock raises during teardown and fails tests that had
            # already passed, which is a fake being wrong about the thing it stands in for.
            if callback in listeners:
                listeners.remove(callback)

        return unsubscribe

    client.add_listener.side_effect = add_listener
    return client


@pytest.fixture
def config_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Processor",
        data={"host": "10.0.0.1"},
        unique_id="TESTSN0001",
    )
    entry.add_to_hass(hass)
    return entry
