"""The base every HTP-1 entity inherits.

It carries the device link, availability, and the third of the three change-gating layers.

That third layer is not an optimisation. The live system fans every state change out to roughly
fifty wall panels, so an entity that rewrites its state when nothing it displays has moved is a
performance defect. The mirror drops no-op assignments, the client only calls out when the
resulting change set is non-empty, and this class compares what it would actually report.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Htp1Coordinator


class Htp1Entity(CoordinatorEntity[Htp1Coordinator]):
    """One control or reading on one processor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: Htp1Coordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        entry = coordinator.config_entry
        # Entry-id based, never serial-based. The entry's own unique_id may legitimately change
        # from host to serial later; entity identities must survive that, or an installation
        # loses its history and its entity ids.
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)}
        )
        self._snapshot: tuple[Any, ...] | None = None

    @property
    def available(self) -> bool:
        """Unavailable means we cannot talk to the unit.

        Distinct from unknown, which means we can and it has not said. A field this firmware
        does not carry reports unknown; it must never report unavailable, and it must never
        report a stale value.
        """
        return super().available and self.coordinator.mirror.loaded

    def _state_snapshot(self) -> tuple[Any, ...]:
        """Everything this entity would report, including whether it is available.

        Subclasses extend this. Availability is part of it deliberately: an entity that goes
        unavailable without its reported values changing still has to tell Home Assistant.
        """
        return (self.available,)

    def _handle_coordinator_update(self) -> None:
        snapshot = self._state_snapshot()
        if snapshot == self._snapshot:
            return
        self._snapshot = snapshot
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Seed the snapshot so the first push after load is compared against what was actually
        # written at load, rather than against nothing.
        self._snapshot = self._state_snapshot()
