"""Shutdown, kept well away from everything else.

The unit has two ways of going quiet and only one of them is recoverable:

- **Sleep** turns off the front panel and waits for a fast wake-up. The network stays up, so
  Home Assistant keeps seeing the device and can turn it back on. That is what `turn_off` does.
- **Shutdown** is an orderly power-down into a low-power state, and **it takes the network with
  it**. Measured on 2026-08-16: the unit stopped answering on port 80 within ten seconds, was
  still silent four minutes later, and had to be started from its front panel.

So shutdown is not a mode of `turn_off`. It is its own button, and it is **disabled by
default**, because the entity registry's enable step is the only real confirmation gate Home
Assistant offers a button. Someone has to deliberately enable it once per processor before it
can appear on a dashboard or be reachable from an automation.

If that ever feels like too much friction, the one-line change is
`entity_registry_enabled_default`. It is set the cautious way because the failure mode is
someone walking to another room.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Htp1ConfigEntry
from .const import POWER_OFF_SHUTDOWN
from .coordinator import Htp1Coordinator
from .entity import Htp1Entity

PARALLEL_UPDATES = 0

SHUTDOWN = ButtonEntityDescription(
    key="shutdown",
    translation_key="shutdown",
    entity_category=EntityCategory.CONFIG,
    # The gate. See the module docstring.
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Htp1ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([Htp1ShutdownButton(entry.runtime_data.coordinator)])


class Htp1ShutdownButton(Htp1Entity, ButtonEntity):
    """Power the processor down completely, ending communication with it."""

    entity_description = SHUTDOWN

    def __init__(self, coordinator: Htp1Coordinator) -> None:
        super().__init__(coordinator, SHUTDOWN.key)
        self.entity_description = SHUTDOWN

    async def async_press(self) -> None:
        """Write the shutdown action.

        The unit will stop answering almost immediately, so the write is not confirmed and the
        entities go unavailable — which is the honest outcome rather than a failure. Nothing
        here can bring it back; that needs the front panel.
        """
        await self.coordinator.async_write("/powerAction", POWER_OFF_SHUTDOWN)
