"""The processor as a media player: power, volume, mute, source and sound mode.

This is the entity everything else is secondary to, and the one that carries the hard-won
volume behaviour. Two things it deliberately does not do:

It does not derive `volume_level` from what was last requested. The unit's confirmed dB is the
truth, and reporting a requested value would let the slider disagree with the front panel.

It does not offer a source list built from dictionary order. JSON object order is not a
contract, so a unit that reordered its `/inputs` map between documents would reshuffle every
dropdown in the house on reconnect.
"""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Htp1ConfigEntry
from .const import POWER_OFF_KEEPS_NETWORK
from .coordinator import Htp1Coordinator
from .entity import Htp1Entity
from .htp1 import db_to_fraction, sound_mode_options, source_options

# Writes are already coalesced and serialised inside the client, so Home Assistant does not
# need to add a second layer of throttling on top.
PARALLEL_UPDATES = 0

_BASE_FEATURES = (
    MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Htp1ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([Htp1MediaPlayer(entry.runtime_data.coordinator)])


class Htp1MediaPlayer(Htp1Entity, MediaPlayerEntity):
    """One processor."""

    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    # The device carries the name; this is the processor itself rather than a sub-control.
    _attr_name = None

    def __init__(self, coordinator: Htp1Coordinator) -> None:
        super().__init__(coordinator, "media_player")
        self._attr_translation_key = None

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """`TURN_ON` is only offered if the unit can hear us while it is off.

        Whether its network stack survives `powerIsOn: false` is HW-01, still unmeasured. We
        ship assuming it does, because being wrong that way means the write simply never lands
        — the safe direction. The constant is referenced only here, so flipping it is one line.
        """
        if POWER_OFF_KEEPS_NETWORK:
            return _BASE_FEATURES | MediaPlayerEntityFeature.TURN_ON
        return _BASE_FEATURES

    # -- state ---------------------------------------------------------------------------

    @property
    def state(self) -> MediaPlayerState | None:
        power = self.coordinator.optimistic("/powerIsOn")
        if power is None:
            return None
        # `ON` rather than `PLAYING`: this is a pre-processor, and inferring playback from a
        # decoded format would claim more than the unit actually tells us.
        return MediaPlayerState.ON if power else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float | None:
        """Derived from the unit's confirmed dB over its own reported range."""
        volume = self.coordinator.optimistic("/volume")
        volume_range = self.coordinator.volume_range
        if volume is None or volume_range is None:
            return None
        return db_to_fraction(volume, *volume_range)

    @property
    def volume_step(self) -> float:
        """One dB, expressed as a fraction of the unit's range.

        The default 0.1 would be a ten-percent jump — around five dB here, which is a lot in a
        room.
        """
        volume_range = self.coordinator.volume_range
        if volume_range is None or volume_range[1] <= volume_range[0]:
            return 0.1
        return 1.0 / (volume_range[1] - volume_range[0])

    @property
    def is_volume_muted(self) -> bool | None:
        return self.coordinator.optimistic("/muted")

    @property
    def source(self) -> str | None:
        current = self.coordinator.optimistic("/input")
        if current is None:
            return None
        for label, key in self._sources().items():
            if key == current:
                return label
        return None

    @property
    def source_list(self) -> list[str]:
        return list(self._sources())

    @property
    def sound_mode(self) -> str | None:
        current = self.coordinator.optimistic("/upmix/select")
        if current is None:
            return None
        for label, key in self._sound_modes().items():
            if key == current:
                return label
        return None

    @property
    def sound_mode_list(self) -> list[str]:
        return list(self._sound_modes())

    def _sources(self) -> dict[str, str]:
        return source_options(self.coordinator.mirror.inputs, self.coordinator.optimistic("/input"))

    def _sound_modes(self) -> dict[str, str]:
        return sound_mode_options(
            self.coordinator.mirror.upmix_visible, self.coordinator.optimistic("/upmix/select")
        )

    def _state_snapshot(self) -> tuple:
        return (
            *super()._state_snapshot(),
            self.state,
            self.volume_level,
            self.is_volume_muted,
            self.source,
            tuple(self.source_list),
            self.sound_mode,
            tuple(self.sound_mode_list),
        )

    # -- commands ------------------------------------------------------------------------

    async def async_turn_on(self) -> None:
        await self.coordinator.async_set_power(True)

    async def async_turn_off(self) -> None:
        await self.coordinator.async_set_power(False)

    async def async_set_volume_level(self, volume: float) -> None:
        await self.coordinator.async_set_volume_fraction(volume)

    async def async_volume_up(self) -> None:
        await self._step_volume(+1)

    async def async_volume_down(self) -> None:
        await self._step_volume(-1)

    async def _step_volume(self, delta: int) -> None:
        """Step in whole dB.

        The unit has no relative volume verb, so a step is read-modify-write. Working in dB
        rather than in fractions means a step is exactly one dB rather than whatever a fraction
        happens to round to.
        """
        current = self.coordinator.optimistic("/volume")
        volume_range = self.coordinator.volume_range
        if current is None or volume_range is None:
            return
        low, high = volume_range
        await self.coordinator.async_write("/volume", int(max(low, min(high, current + delta))))

    async def async_mute_volume(self, mute: bool) -> None:
        await self.coordinator.async_write("/muted", mute)

    async def async_select_source(self, source: str) -> None:
        key = self._sources().get(source)
        if key is not None:
            await self.coordinator.async_write("/input", key)

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        key = self._sound_modes().get(sound_mode)
        if key is not None:
            await self.coordinator.async_write("/upmix/select", key)
