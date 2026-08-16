"""The diagnostics dump.

This exists to make bug reports cheap, which means it is meant to be pasted into a public issue.
Anything secret that reaches it is published.

The HTP-1 has no credentials, so the usual redaction list is empty and the real exposure is
**topology**: the unit's name, the owner's input labels, their Dirac slot names, the serial
number, and the address. Those are what this redacts, and `test_diagnostics_leak_no_site_data`
is what keeps them redacted.

What stays is what a maintainer actually needs: firmware, connection state, the shape of the
document, and which fields this firmware does and does not report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .htp1.mso import TRACKED_PATHS

if TYPE_CHECKING:
    from . import Htp1ConfigEntry

TO_REDACT = {CONF_HOST, "host", "serial", "unit_name"}

# Mirror fields whose value is the owner's words rather than the device's behaviour.
_SITE_DATA_FIELDS = {"unit_name", "serial"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: Htp1ConfigEntry
) -> dict[str, Any]:
    runtime = entry.runtime_data
    client = runtime.client
    mirror = client.mirror

    return {
        "entry": {
            # Both data and options, because options are just as capable of holding something
            # site-specific as data is.
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
            "unique_id_kind": "serial"
            if entry.unique_id and not entry.unique_id.startswith("host-")
            else "host",
        },
        "connection": {
            "connected": client.connected,
            "reconnecting": client.reconnecting,
            "document_loaded": mirror.loaded,
            "pending_writes": len(client.pending_paths),
        },
        "firmware": {
            "system": mirror.get("system_version"),
            "av_controller": mirror.get("av_controller"),
        },
        "state": {
            # Values, but only for fields that describe the device rather than the house.
            name: mirror.get(name)
            for field in TRACKED_PATHS.values()
            for name in (field.name,)
            if name not in _SITE_DATA_FIELDS
        },
        "shape": {
            # Counts, not names. How many inputs exist and how many are visible is diagnostic;
            # what they are called is the owner's business.
            "inputs_total": len(mirror.inputs),
            "inputs_visible": sum(1 for info in mirror.inputs.values() if info.visible),
            "dirac_slots": len(mirror.dirac_slots),
            "dirac_slots_named": sum(1 for slot in mirror.dirac_slots if slot.name),
            "upmix_modes_visible": sum(1 for shown in mirror.upmix_visible.values() if shown),
            "fields_reported": sorted(
                field.name for field in TRACKED_PATHS.values() if mirror.has(field.name)
            ),
            "fields_absent": sorted(
                field.name for field in TRACKED_PATHS.values() if not mirror.has(field.name)
            ),
        },
        # A declared codec that disagreed with what this unit sent. Worth surfacing: it is how
        # a firmware difference shows up as something other than a control that does nothing.
        "codec_mismatches": list(mirror.mismatches),
    }
