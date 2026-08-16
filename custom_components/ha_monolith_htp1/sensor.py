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

Every sensor here describes a **live signal**, which is why `native_value` blanks all of them
when the unit reports itself off. See the note there: the unit does not stop describing a
soundtrack just because it went to sleep.
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

# What the video sensors say when the unit reports no picture on the selected input.
#
# Deliberately "No Signal" rather than anything about cabling. The processor cannot distinguish
# an unplugged input from a connected source that has gone to sleep — both produce the same
# padded dashes — so the wording has to be true of both, and a claim about what is plugged in
# would be a guess dressed up as a reading.
NO_SIGNAL = "No Signal"


@dataclass(frozen=True, kw_only=True)
class Htp1SensorDescription(SensorEntityDescription):
    """A reading, named by the mirror field it shows."""

    field: str
    # What an **empty** reading means, when a video signal is present.
    #
    # The unit writes three different things, and only two of them were noticed at first:
    #
    #   "HDR10"   an actual reading
    #   ""        there is a signal, and this attribute does not apply to it
    #   "-----"   there is no signal at all, padded to the field's width
    #
    # For most fields the middle case really is unknown — a unit reporting a signal but no
    # `VideoBitDepth` has told us nothing about bit depth. For HDR it is the answer: a picture
    # that carries no HDR metadata is SDR, and saying so is the whole point of the sensor.
    #
    # Left None everywhere else on purpose. Inventing a value for a field the unit declined to
    # report would be guessing, and this is the one place where the absence has a name.
    empty_means: str | None = None
    # What to say when the unit reports no video signal at all.
    #
    # `unknown` is technically true but reads like a fault, and on a processor with nothing
    # plugged into the selected input it is a permanent state rather than a transient one. The
    # video sensors say so in words instead.
    #
    # Deliberately not applied to the audio sensors: those are blanked when the unit is off, and
    # a processor decoding nothing is a different situation from one with no picture.
    no_signal_means: str | None = None


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
        no_signal_means=NO_SIGNAL,
    ),
    Htp1SensorDescription(
        key="hdr_status",
        translation_key="hdr_status",
        field="hdr_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        # A picture with no HDR metadata is SDR. Measured on five units: three showed `""`
        # here while carrying a real 720p60Hz signal, one showed `HDR10`, and the one with no
        # signal at all showed `--`.
        empty_means="SDR",
        no_signal_means=NO_SIGNAL,
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
        """`None` whenever the reading cannot mean anything.

        Two ways that happens, both measured on firmware 2.1.2 on 2026-08-16.

        A sleeping unit keeps reporting the last thing it decoded. Asleep, it still claimed
        `Dolby Surround` and `5.1.2` — and pushed listening-format changes twice inside a
        twenty-second window. Showing that is worse than showing nothing: a dark processor
        would sit on a wall panel announcing a soundtrack. Blanking also means those pushes
        stop reaching the panels at all, because every one of them now compares equal.

        And a field the unit has no reading for is filled with dashes, whose width follows the
        field rather than the meaning — `--`, `---`, `-----`. Only-dashes is not a reading.
        The test is deliberately "nothing but dashes and spaces" rather than "contains a dash",
        so a real value like `1920x1080p-60` still reports itself.

        An **empty** string is a third thing, and treating it as a fourth spelling of the second
        was a defect: it means the unit has a signal but this attribute does not apply to it.
        For most fields that is still unknown. For HDR it is SDR — see `empty_means`.

        The video sensors then name the no-signal case rather than reporting `unknown`, which on
        an input with nothing on it is a permanent state that reads like a fault. Power is still
        checked first: a sleeping processor is off, not unplugged, and must not claim otherwise.
        """
        # `is False` and not a falsy test: a firmware that never reports power must not blank
        # every sensor it does report.
        if self.coordinator.optimistic("/powerIsOn") is False:
            return None
        value = self.coordinator.mirror.get(self.entity_description.field)
        if not isinstance(value, str) or value.strip(" -"):
            return value

        description = self.entity_description
        if self._video_signal_present():
            # Blank despite a picture: only HDR has a name for that.
            if value == "" and description.empty_means:
                return description.empty_means
            return None
        return description.no_signal_means

    def _video_signal_present(self) -> bool:
        """Is the unit seeing a picture at all?

        Guarded on the resolution rather than trusting `""` on its own. Empty was only ever
        observed alongside a live signal, but a firmware that reported it on a dead input would
        otherwise make this sensor announce SDR about nothing.
        """
        resolution = self.coordinator.mirror.get("video_resolution")
        return isinstance(resolution, str) and bool(resolution.strip(" -"))

    def _state_snapshot(self) -> tuple:
        return (*super()._state_snapshot(), self.native_value)
