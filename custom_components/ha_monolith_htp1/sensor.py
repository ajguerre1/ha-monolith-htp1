"""Read-only status: what the processor says it is decoding, and what it is sending to the TV.

**Every value here is free text, deliberately.** The unit's own vocabulary includes
`ENCListeningFormat` values like `5.2.2t` and `SurroundMode` values like `Native Dolby ATMOS`,
measured across five units on firmware 2.1.2. Any enumeration written today would be a bug on a
firmware nobody has seen yet, and the cost of being wrong is an entity that reports `unknown`
for something the unit is perfectly happy to describe.

Four of these are **disabled by default**. Sample rates and program format change on every
content transition, and with five units feeding roughly fifty wall panels that is a lot of
fan-out for something nobody automates on. Anyone who wants one enables it in the entity
settings, which is exactly what the entity registry is for — and why this is not an option in
the config flow.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Htp1ConfigEntry
from .coordinator import Htp1Coordinator
from .entity import Htp1Entity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class Htp1SensorDescription(SensorEntityDescription):
    """A reading, named by the mirror field it shows."""

    field: str


SENSORS: tuple[Htp1SensorDescription, ...] = (
    # Shown by default: what most people would actually look at.
    Htp1SensorDescription(
        key="surround_mode",
        translation_key="surround_mode",
        field="surround_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    Htp1SensorDescription(
        key="source_program",
        translation_key="source_program",
        field="source_program",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    Htp1SensorDescription(
        key="listening_format",
        translation_key="listening_format",
        field="listening_format",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Off by default: these move on every content change.
    Htp1SensorDescription(
        key="program_format",
        translation_key="program_format",
        field="program_format",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    Htp1SensorDescription(
        key="input_sample_rate",
        translation_key="input_sample_rate",
        field="input_sample_rate",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    Htp1SensorDescription(
        key="output_sample_rate",
        translation_key="output_sample_rate",
        field="output_sample_rate",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    Htp1SensorDescription(
        key="dirac_status",
        translation_key="dirac_status",
        field="dirac_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        # Duplicates what the Dirac state select already reads back.
        entity_registry_enabled_default=False,
    ),
    # Video. Absent entirely on firmware 1.13.x, so these may simply not be created.
    Htp1SensorDescription(
        key="video_resolution",
        translation_key="video_resolution",
        field="video_resolution",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    Htp1SensorDescription(
        key="hdr_status",
        translation_key="hdr_status",
        field="hdr_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    Htp1SensorDescription(
        key="video_color_space",
        translation_key="video_color_space",
        field="video_color_space",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Htp1ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        Htp1Sensor(coordinator, description)
        for description in SENSORS
        # A field this firmware does not report gets no entity at all, rather than one that is
        # permanently unknown. Firmware 1.13.x has no video block whatsoever.
        if coordinator.mirror.has(description.field)
    )


class Htp1Sensor(Htp1Entity, SensorEntity):
    entity_description: Htp1SensorDescription

    def __init__(self, coordinator: Htp1Coordinator, description: Htp1SensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | None:
        return self.coordinator.mirror.get(self.entity_description.field)

    def _state_snapshot(self) -> tuple:
        return (*super()._state_snapshot(), self.native_value)
