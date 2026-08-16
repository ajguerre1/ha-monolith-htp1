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
from custom_components.ha_monolith_htp1.htp1.mso import MsoMirror

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
    client.optimistic.side_effect = lambda path: mirror.get(path.strip("/"))

    client.async_start = AsyncMock()
    client.async_stop = AsyncMock()
    client.async_refresh = AsyncMock()
    client.async_write = AsyncMock()

    listeners: list = []
    client.listeners = listeners

    def add_listener(callback):
        listeners.append(callback)
        return lambda: listeners.remove(callback)

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
