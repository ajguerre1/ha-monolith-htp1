"""The Monolith HTP-1 integration.

Control for Monoprice Monolith HTP-1 AV processors over the unit's WebSocket interface.

Setup makes **one** connection attempt and raises `ConfigEntryNotReady` if it fails, so Home
Assistant owns the retry cadence. The client's own reconnect ladder starts only once a first
document has arrived — two backoff loops that know nothing about each other would be worse than
one.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, MANUFACTURER, MODEL, SETUP_TIMEOUT
from .coordinator import Htp1Coordinator
from .htp1.client import Htp1Client, Htp1Error

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class Htp1Runtime:
    """Everything one config entry owns while it is loaded."""

    client: Htp1Client
    coordinator: Htp1Coordinator


type Htp1ConfigEntry = ConfigEntry[Htp1Runtime]


async def async_setup_entry(hass: HomeAssistant, entry: Htp1ConfigEntry) -> bool:
    """Connect to one processor and register it."""
    host = entry.data[CONF_HOST]
    client = Htp1Client(
        async_get_clientsession(hass),
        host,
        # Per-entry seed, so two units never reconnect in lockstep after a network blip.
        seed=entry.entry_id,
        allow_writes=True,
    )

    try:
        async with asyncio.timeout(SETUP_TIMEOUT):
            await client.async_start()
    except (Htp1Error, TimeoutError) as err:
        raise ConfigEntryNotReady(f"cannot reach {host}: {err}") from err

    # From here the client holds a socket. Home Assistant does not call async_unload_entry for
    # a setup that raised, and it retries on a backoff — so anything that fails below must hand
    # the session back, or every attempt leaks one to a unit with a finite number of them.
    try:
        coordinator = Htp1Coordinator(hass, entry, client)
        entry.runtime_data = Htp1Runtime(client=client, coordinator=coordinator)
        coordinator.async_set_updated_data(client.mirror)
        _register_device(hass, entry, client)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await client.async_stop()
        raise

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: Htp1ConfigEntry) -> bool:
    """Stop the client and let go of the socket."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.coordinator.async_shutdown()
    return unloaded


async def _async_options_updated(hass: HomeAssistant, entry: Htp1ConfigEntry) -> None:
    """Apply changed options without reloading.

    Reloading would drop a healthy socket and blank every entity to change a number. The
    coordinator reads options live at command time, so telling the entities to re-read is all
    that is needed.
    """
    entry.runtime_data.coordinator.async_update_listeners()


def _register_device(hass: HomeAssistant, entry: Htp1ConfigEntry, client: Htp1Client) -> None:
    """Register the processor itself.

    Done explicitly in setup rather than left to the first entity, so the device exists even
    before M3 adds any — and so a user can put it in an area immediately. The integration this
    replaces created no device at all, which is why its entities could not inherit an area.
    """
    versions = client.mirror.versions
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=client.mirror.get("unit_name") or entry.title,
        sw_version=versions.system,
        hw_version=versions.av_controller,
        serial_number=versions.serial,
        # The unit serves its own web UI on the same port as the control socket.
        configuration_url=f"http://{client.host}/",
    )
