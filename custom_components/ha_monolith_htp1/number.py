"""Numeric controls: dialogue enhancement and lip sync.

Lip sync carries an unresolved question. The vendor's own client writes `/cal/lipsync` **and**
`/inputs/<current input>/delay` together, and writing only the first is believed to leave the
unit's own display disagreeing with the value it is using. That is HW-06, still unmeasured
because settling it needs a write to the lab unit.

Until it is settled this writes only `/cal/lipsync`, which is the conservative choice: one
documented path, no guess about a second. The constant below is the single place to change if
the measurement says otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Htp1ConfigEntry
from .coordinator import Htp1Coordinator
from .entity import Htp1Entity
from .htp1.mso import TRACKED_PATHS

PARALLEL_UPDATES = 0

# HW-06. See the module docstring: flip this only once a write test on the lab unit says the
# dual write is required.
LIP_SYNC_ALSO_WRITES_INPUT_DELAY = False


@dataclass(frozen=True, kw_only=True)
class Htp1NumberDescription(NumberEntityDescription):
    path: str


NUMBERS: tuple[Htp1NumberDescription, ...] = (
    Htp1NumberDescription(
        key="dialog_enhancement",
        translation_key="dialog_enhancement",
        path="/dialogEnh",
        native_min_value=0,
        native_max_value=6,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
    ),
    Htp1NumberDescription(
        key="lip_sync",
        translation_key="lip_sync",
        path="/cal/lipsync",
        native_min_value=0,
        native_max_value=340,
        native_step=1,
        # A box rather than a slider: 341 positions on a slider is unusable, and lip sync is
        # something people set to a specific measured number.
        mode=NumberMode.BOX,
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
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
        Htp1Number(coordinator, description)
        for description in NUMBERS
        if coordinator.mirror.has(_field_for(description.path))
    )


def _field_for(path: str) -> str:
    field = TRACKED_PATHS.get(path)
    return field.name if field else ""


class Htp1Number(Htp1Entity, NumberEntity):
    entity_description: Htp1NumberDescription

    def __init__(self, coordinator: Htp1Coordinator, description: Htp1NumberDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.optimistic(self.entity_description.path)
        return None if value is None else float(value)

    def _state_snapshot(self) -> tuple:
        return (*super()._state_snapshot(), self.native_value)

    async def async_set_native_value(self, value: float) -> None:
        # Every path here takes an integer; sending 40.0 where the unit expects 40 is asking
        # for a firmware to be fussy about it.
        await self.coordinator.async_write(self.entity_description.path, int(value))
