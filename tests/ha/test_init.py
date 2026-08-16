"""Setting the entry up, tearing it down, and what happens in between.

The failure that matters most here is not a crash. It is a setup that fails *after* the client
has a socket: Home Assistant does not call `async_unload_entry` for a setup that raised, and it
retries on a backoff, so every attempt would leak a session to a unit that has a finite number
of them. `test_a_failed_setup_closes_the_client` is what keeps that closed.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr

from custom_components.ha_monolith_htp1.const import DOMAIN
from custom_components.ha_monolith_htp1.htp1.client import Htp1ConnectionError

PATCH_CLIENT = "custom_components.ha_monolith_htp1.Htp1Client"


async def _setup(hass, entry, client):
    with patch(PATCH_CLIENT, return_value=client):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_setup_creates_the_entry_and_device(hass, config_entry, mock_client):
    """AC-30, AC-35."""
    await _setup(hass, config_entry, mock_client)

    assert config_entry.state is ConfigEntryState.LOADED
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "TESTSN0001")})
    assert device is not None
    assert device.manufacturer == "Monoprice"
    assert device.model == "Monolith HTP-1"
    assert device.serial_number == "TESTSN0001"
    assert device.sw_version == "V2.1.1"
    # The unit serves its own web UI, and a link to it is more useful than none.
    assert device.configuration_url == "http://10.0.0.1/"


async def test_the_device_is_named_from_the_unit(hass, config_entry, mock_client):
    """The integration this replaces created no device at all, so nothing had a name."""
    await _setup(hass, config_entry, mock_client)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "TESTSN0001")})
    assert device.name == "Test Processor"


async def test_runtime_data_is_used(hass, config_entry, mock_client):
    """AC-34. `hass.data[DOMAIN][entry_id]` is the pattern this replaced."""
    await _setup(hass, config_entry, mock_client)
    assert config_entry.runtime_data.client is mock_client
    assert config_entry.runtime_data.coordinator is not None
    assert DOMAIN not in hass.data or config_entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_an_unreachable_unit_defers_setup(hass, config_entry, mock_client):
    """AC-31. Home Assistant retries a ConfigEntryNotReady; it does not retry a hard failure."""
    mock_client.async_start.side_effect = Htp1ConnectionError("unreachable")

    await _setup(hass, config_entry, mock_client)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_failed_setup_closes_the_client(hass, config_entry, mock_client):
    """AC-32. Every retry would otherwise leak a socket to a unit with a finite number."""
    with patch(
        "custom_components.ha_monolith_htp1.Htp1Coordinator", side_effect=RuntimeError("boom")
    ):
        await _setup(hass, config_entry, mock_client)

    assert config_entry.state is not ConfigEntryState.LOADED
    mock_client.async_stop.assert_awaited()


async def test_unload_stops_the_client(hass, config_entry, mock_client):
    """AC-33."""
    await _setup(hass, config_entry, mock_client)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    mock_client.async_stop.assert_awaited()


async def test_the_coordinator_does_not_poll(hass, config_entry, mock_client):
    """AC-36. An idle connection sent zero bytes over ninety seconds; polling is pure waste."""
    await _setup(hass, config_entry, mock_client)
    assert config_entry.runtime_data.coordinator.update_interval is None


async def test_a_push_updates_the_coordinator(hass, config_entry, mock_client):
    """AC-37. Nothing is requested; the unit simply says what changed."""
    await _setup(hass, config_entry, mock_client)
    coordinator = config_entry.runtime_data.coordinator

    mock_client.mirror.apply_ops([{"op": "replace", "path": "/volume", "value": -31}])
    for listener in mock_client.listeners:
        listener(frozenset({"volume"}))
    await hass.async_block_till_done()

    assert coordinator.last_update_success is True
    assert coordinator.mirror.get("volume") == -31


async def test_entities_go_unavailable_and_recover(hass, config_entry, mock_client, caplog):
    """AC-38, AC-39. One line per outage, one on recovery — not one per retry."""
    await _setup(hass, config_entry, mock_client)
    coordinator = config_entry.runtime_data.coordinator

    with caplog.at_level(logging.INFO):
        mock_client.connected = False
        for _ in range(6):  # six failed reconnects across the ladder
            for listener in mock_client.listeners:
                listener(frozenset())
        await hass.async_block_till_done()
        assert coordinator.last_update_success is False

        mock_client.connected = True
        for listener in mock_client.listeners:
            listener(frozenset({"volume"}))
        await hass.async_block_till_done()

    assert coordinator.last_update_success is True
    reconnected = [r for r in caplog.records if "Reconnected" in r.getMessage()]
    assert len(reconnected) == 1, "recovery must be logged exactly once"


async def test_changing_options_does_not_reload_the_entry(hass, config_entry, mock_client):
    """AC-48. Reloading would drop a healthy socket and blank every entity to set a number."""
    await _setup(hass, config_entry, mock_client)
    client_before = config_entry.runtime_data.client

    hass.config_entries.async_update_entry(config_entry, options={"max_volume_db": -20})
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.client is client_before, "the entry was reloaded"
    mock_client.async_stop.assert_not_awaited()


@pytest.mark.parametrize(
    ("fraction", "expected"),
    [(1.0, 0), (0.0, -50), (0.5, -25)],
)
async def test_volume_is_written_in_device_units(
    hass, config_entry, mock_client, fraction, expected
):
    """The unit takes integer dB over its own range, not a percentage."""
    await _setup(hass, config_entry, mock_client)
    await config_entry.runtime_data.coordinator.async_set_volume_fraction(fraction)
    mock_client.async_write.assert_awaited_with("/volume", expected)


async def test_the_volume_ceiling_limits_what_is_sent(hass, config_entry, mock_client):
    """The reported level still comes from the unit's real range; only writes are clamped."""
    hass.config_entries.async_update_entry(config_entry, options={"max_volume_db": -20})
    await _setup(hass, config_entry, mock_client)

    await config_entry.runtime_data.coordinator.async_set_volume_fraction(1.0)

    mock_client.async_write.assert_awaited_with("/volume", -20)


async def test_turning_off_sleeps_by_default(hass, config_entry, mock_client):
    """Sleep, never shutdown.

    Shutdown takes the network with it — measured on 2026-08-16, the unit was silent for four
    minutes and needed its front panel. Mapping `turn_off` to that would mean Home Assistant
    lost the device every time somebody turned a room off, with no way to turn it back on.
    """
    await _setup(hass, config_entry, mock_client)

    await config_entry.runtime_data.coordinator.async_set_power(False)

    mock_client.async_write.assert_awaited_with("/powerAction", "sleep")


async def test_turning_off_can_be_configured_to_shut_down(hass, config_entry, mock_client):
    """Available, but only because someone chose it explicitly in the options."""
    hass.config_entries.async_update_entry(config_entry, options={"power_off_action": "off"})
    await _setup(hass, config_entry, mock_client)

    await config_entry.runtime_data.coordinator.async_set_power(False)

    mock_client.async_write.assert_awaited_with("/powerAction", "off")


async def test_do_nothing_really_does_nothing(hass, config_entry, mock_client):
    """A stray automation must not be able to silence a room that opted out."""
    hass.config_entries.async_update_entry(config_entry, options={"power_off_action": "do_nothing"})
    await _setup(hass, config_entry, mock_client)
    mock_client.async_write.reset_mock()

    await config_entry.runtime_data.coordinator.async_set_power(False)

    mock_client.async_write.assert_not_awaited()
