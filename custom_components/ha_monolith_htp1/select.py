"""Dropdowns: the Dirac calibration slot, Dirac's own state, and night mode.

The Dirac slot is the one with a trap in it. `/cal/currentdiracslot` is a **0-based index** into
a six-row array, and on all five units measured here **none of the slots are named**. So an
option list built from names alone would be six empty strings, and resolving the current slot
by name would match the wrong one immediately.

Options are therefore labelled by index — `0 - Slot 0`, or `0 - Reference` when a name exists —
and the current slot is resolved by position. The prefix also makes duplicate names unique for
free, which matters because nothing stops an installer calling two slots "Movie".
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Htp1ConfigEntry
from .coordinator import Htp1Coordinator
from .entity import Htp1Entity
from .htp1 import dirac_slot_options
from .htp1.mso import TRACKED_PATHS

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class Htp1SelectDescription(SelectEntityDescription):
    """A select over a fixed set of wire values."""

    path: str
    values: tuple[str, ...]


# The unit's own vocabulary. Labels come from `strings.json` via the translation key, so the
# wire value never reaches a user's screen.
FIXED_SELECTS: tuple[Htp1SelectDescription, ...] = (
    Htp1SelectDescription(
        key="dirac_state",
        translation_key="dirac_state",
        path="/cal/diracactive",
        values=("off", "on", "bypass"),
        entity_category=EntityCategory.CONFIG,
    ),
    Htp1SelectDescription(
        key="night_mode",
        translation_key="night_mode",
        path="/night",
        values=("off", "auto", "on"),
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Htp1ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[SelectEntity] = [
        Htp1FixedSelect(coordinator, description)
        for description in FIXED_SELECTS
        # A firmware that does not report the path does not get a control for it.
        if coordinator.mirror.has(_field_for(description.path))
    ]
    entities.append(Htp1DiracSlotSelect(coordinator))
    async_add_entities(entities)


def _field_for(path: str) -> str:
    """The mirror field name a wire path maps to, for absence checks."""
    field = TRACKED_PATHS.get(path)
    return field.name if field else ""


class Htp1FixedSelect(Htp1Entity, SelectEntity):
    """A select whose options are the same on every unit."""

    entity_description: Htp1SelectDescription

    def __init__(self, coordinator: Htp1Coordinator, description: Htp1SelectDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_options = list(description.values)

    @property
    def current_option(self) -> str | None:
        value = self.coordinator.optimistic(self.entity_description.path)
        # Never report an option that is not in the list: Home Assistant logs an error and the
        # frontend renders the dropdown blank.
        return value if value in self.entity_description.values else None

    def _state_snapshot(self) -> tuple:
        return (*super()._state_snapshot(), self.current_option)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_write(self.entity_description.path, option)


class Htp1DiracSlotSelect(Htp1Entity, SelectEntity):
    """The active Dirac calibration slot, addressed by position."""

    _attr_translation_key = "dirac_slot"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: Htp1Coordinator) -> None:
        super().__init__(coordinator, "dirac_slot")

    def _slots(self) -> dict[str, int]:
        return dirac_slot_options(self.coordinator.mirror.dirac_slots)

    @property
    def options(self) -> list[str]:
        return list(self._slots())

    @property
    def current_option(self) -> str | None:
        """Resolved by index, never by name.

        Options and the current value are derived from the same snapshot in the same call, so
        they cannot drift; an out-of-range index reports nothing rather than the wrong slot,
        because pointing at the wrong calibration is worse than pointing at none.
        """
        index = self.coordinator.optimistic("/cal/currentdiracslot")
        if index is None:
            return None
        for label, slot_index in self._slots().items():
            if slot_index == index:
                return label
        return None

    def _state_snapshot(self) -> tuple:
        return (*super()._state_snapshot(), self.current_option, tuple(self.options))

    async def async_select_option(self, option: str) -> None:
        index = self._slots().get(option)
        if index is not None:
            await self.coordinator.async_write("/cal/currentdiracslot", index)
