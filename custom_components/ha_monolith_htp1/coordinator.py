"""The coordinator: one per config entry, driven by pushes rather than by a clock.

`update_interval` is None. The HTP-1 announces every change from any source, including its own
front panel, and an idle connection was measured sending zero bytes over ninety seconds — so a
poll interval would be pure waste. Updates arrive through the client's change callback and are
handed to `async_set_updated_data`.

This is also where every command lives. Entities stay thin: they know which field they show and
which path they write, and nothing about ranges, ceilings or what "off" means on this unit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_MAX_VOLUME_DB,
    CONF_POWER_OFF_ACTION,
    DEFAULT_POWER_OFF_ACTION,
    DOMAIN,
    POWER_OFF_NOTHING,
    SETUP_TIMEOUT,
)
from .htp1 import MsoMirror, fraction_to_db
from .htp1.client import Htp1Client, Htp1Error

if TYPE_CHECKING:
    from . import Htp1ConfigEntry

_LOGGER = logging.getLogger(__name__)


class Htp1Coordinator(DataUpdateCoordinator[MsoMirror]):
    """Owns the client, publishes its changes, and translates commands into writes."""

    config_entry: Htp1ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: Htp1ConfigEntry, client: Htp1Client) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # No polling. See the module docstring.
            update_interval=None,
            config_entry=entry,
        )
        self.client = client
        self._unsubscribe = client.add_listener(self._handle_change)

    # -- lifecycle -----------------------------------------------------------------------

    async def async_shutdown(self) -> None:
        self._unsubscribe()
        await self.client.async_stop()
        await super().async_shutdown()

    async def _async_update_data(self) -> MsoMirror:
        """Re-request the document.

        Nothing schedules this, but implementing it keeps `async_config_entry_first_refresh`
        working normally and gives `homeassistant.update_entity` a real meaning — which is also
        the user's way out of a client that has exhausted its parse budget.
        """
        try:
            async with asyncio.timeout(SETUP_TIMEOUT):
                await self.client.async_refresh()
        except Htp1Error as err:
            raise UpdateFailed(f"cannot read {self.client.host}: {err}") from err
        except TimeoutError as err:
            raise UpdateFailed(f"{self.client.host} did not answer in time") from err
        return self.client.mirror

    # -- push handling -------------------------------------------------------------------

    @callback
    def _handle_change(self, changed: frozenset[str]) -> None:
        """Called by the client whenever something actually moved."""
        if not self.client.connected:
            self._note_disconnected()
            return

        # `async_set_updated_data` never enters `_async_refresh`, which is where the
        # coordinator's own recovery logging lives — so the "back again" line is ours to emit.
        was_down = not self.last_update_success
        self.async_set_updated_data(self.client.mirror)
        if was_down:
            _LOGGER.info("Reconnected to %s", self.client.host)

    @callback
    def _note_disconnected(self) -> None:
        """Mark the unit unavailable.

        `async_set_update_error` is self-throttling: it logs only when the previous update
        succeeded and debugs thereafter, so calling it on every failed reconnect across a
        2-to-60-second ladder produces one message per outage rather than hundreds.
        """
        self.async_set_update_error(UpdateFailed(f"lost the connection to {self.client.host}"))

    # -- reads ---------------------------------------------------------------------------

    @property
    def mirror(self) -> MsoMirror:
        return self.client.mirror

    def optimistic(self, path: str) -> Any:
        """What a path is believed to hold, including writes not yet confirmed."""
        return self.client.optimistic(path)

    @property
    def volume_range(self) -> tuple[float, float] | None:
        """The unit's own `[vpl, vph]`, or None if it has not said.

        Read live rather than assumed: measured at -50/0 on all five units here, but the values
        are user-configurable per unit and nothing may hardcode them.
        """
        low, high = self.mirror.get("vpl"), self.mirror.get("vph")
        if low is None or high is None:
            return None
        return float(low), float(high)

    # -- commands ------------------------------------------------------------------------

    async def async_set_volume_fraction(self, fraction: float) -> None:
        """Set volume from a Home Assistant 0..1 level.

        The ceiling is applied to what we *send*, not to how the level is derived, so the
        reported position still matches the unit's own display.
        """
        volume_range = self.volume_range
        if volume_range is None:
            raise HomeAssistantError(f"{self.client.host} has not reported its volume range")
        low, high = volume_range
        ceiling = self.config_entry.options.get(CONF_MAX_VOLUME_DB)
        if ceiling is not None:
            high = min(high, float(ceiling))
        await self._write("/volume", fraction_to_db(fraction, low, high))

    async def async_set_power(self, on: bool) -> None:
        """Turn on by setting power; turn off by the configured action.

        Off is `/powerAction`, not `/powerIsOn: false` — the unit distinguishes standby from
        sleep, and the installer may want neither.
        """
        if on:
            await self._write("/powerIsOn", True)
            return
        action = self.config_entry.options.get(CONF_POWER_OFF_ACTION, DEFAULT_POWER_OFF_ACTION)
        if action == POWER_OFF_NOTHING:
            _LOGGER.debug(
                "power off requested for %s, but the entry is configured to do nothing",
                self.client.host,
            )
            return
        await self._write("/powerAction", action)

    async def async_write(self, path: str, value: Any) -> None:
        """Write one path. Entities go through here rather than touching the client."""
        await self._write(path, value)

    async def _write(self, path: str, value: Any) -> None:
        try:
            await self.client.async_write(path, value)
        except Htp1Error as err:
            # Surfaced to the caller, so a service call that could not be delivered fails
            # visibly instead of appearing to succeed.
            raise HomeAssistantError(str(err)) from err
