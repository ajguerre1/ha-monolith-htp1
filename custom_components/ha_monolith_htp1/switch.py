"""Two-state controls: loudness, bass enhancement and tone control.

The wire representation is not uniform, and that is the unit's doing rather than ours.
`/loudness` and `/bassenhance` are the **strings** "on" and "off"; `/eq/tc` is a real JSON
boolean — measured on all five units, firmware 2.1.2. The vendored codecs absorb that, so
nothing here has to know which is which.

A value the codec cannot read reports **unknown**, never off. A switch that quietly claims to
be off when it does not know is the kind of thing an automation acts on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Htp1ConfigEntry
from .coordinator import Htp1Coordinator
from .entity import Htp1Entity
from .htp1.models import BOOL_CODEC, ON_OFF_CODEC, Codec
from .htp1.mso import TRACKED_PATHS

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class Htp1SwitchDescription(SwitchEntityDescription):
    path: str
    codec: Codec


SWITCHES: tuple[Htp1SwitchDescription, ...] = (
    Htp1SwitchDescription(
        key="loudness",
        translation_key="loudness",
        path="/loudness",
        codec=ON_OFF_CODEC,
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
    ),
    Htp1SwitchDescription(
        key="bass_enhance",
        translation_key="bass_enhance",
        path="/bassenhance",
        codec=ON_OFF_CODEC,
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
    ),
    Htp1SwitchDescription(
        key="tone_control",
        translation_key="tone_control",
        # Measured as a JSON boolean on firmware 2.1.2 across five units. Its two neighbours
        # are strings, so this asymmetry is real and was worth confirming rather than assuming.
        path="/eq/tc",
        codec=BOOL_CODEC,
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Htp1ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        Htp1Switch(coordinator, description)
        for description in SWITCHES
        if coordinator.mirror.has(_field_for(description.path))
    )


def _field_for(path: str) -> str:
    field = TRACKED_PATHS.get(path)
    return field.name if field else ""


class Htp1Switch(Htp1Entity, SwitchEntity):
    entity_description: Htp1SwitchDescription

    def __init__(self, coordinator: Htp1Coordinator, description: Htp1SwitchDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """None when the value cannot be read — unknown, not off."""
        return self.coordinator.optimistic(self.entity_description.path)

    def _state_snapshot(self) -> tuple:
        return (*super()._state_snapshot(), self.is_on)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, value: bool) -> None:
        # The client encodes through the same codec on the way out, so this stays a bool.
        await self.coordinator.async_write(self.entity_description.path, value)
