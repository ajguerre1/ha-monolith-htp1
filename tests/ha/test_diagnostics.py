"""The diagnostics dump exists to be pasted into a public issue.

So the test that matters is not "does it contain useful things" but "does it contain the
owner's house". The HTP-1 has no credentials; what leaks here is topology — the unit's name,
the input labels someone typed, their Dirac slot names, the serial, and the address.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

PATCH_CLIENT = "custom_components.ha_monolith_htp1.Htp1Client"


async def _loaded(hass, entry, client):
    with patch(PATCH_CLIENT, return_value=client):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_diagnostics_leak_no_site_data(
    hass, hass_client, config_entry, mock_client, document
):
    """AC-45. Every string in the document that belongs to the owner rather than the device."""
    await _loaded(hass, config_entry, mock_client)
    dump = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    blob = json.dumps(dump)

    secrets = [
        config_entry.data["host"],
        document["unitname"],
        document["versions"]["SerialNumber"],
        *(i["label"] for i in document["inputs"].values() if i["label"]),
        *(s.get("name") for s in document["cal"]["slots"] if s.get("name")),
    ]
    leaked = sorted({s for s in secrets if s and s in blob})
    assert not leaked, f"diagnostics leaked site data: {leaked}"


async def test_diagnostics_still_say_something_useful(hass, hass_client, config_entry, mock_client):
    """Redaction that removed everything would be safe and worthless."""
    await _loaded(hass, config_entry, mock_client)
    dump = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    assert dump["connection"]["connected"] is True
    assert dump["firmware"]["system"] == "V2.1.1"
    assert dump["state"]["volume"] == -25
    assert dump["shape"]["inputs_total"] == 21
    assert dump["shape"]["dirac_slots"] == 6
    assert "surround_mode" in dump["shape"]["fields_reported"]


async def test_diagnostics_report_shape_rather_than_names(
    hass, hass_client, config_entry, mock_client
):
    """How many inputs are visible is diagnostic; what they are called is the owner's business."""
    await _loaded(hass, config_entry, mock_client)
    dump = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    assert dump["shape"]["inputs_visible"] == 7
    assert dump["shape"]["dirac_slots_named"] == 5
    assert "inputs" not in dump["state"], "input labels must not be dumped"


async def test_diagnostics_redact_options_as_well_as_data(
    hass, hass_client, config_entry, mock_client
):
    """Options are as capable of holding something site-specific as data is."""
    hass.config_entries.async_update_entry(config_entry, options={"host": "10.0.0.77"})
    await _loaded(hass, config_entry, mock_client)
    dump = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    assert "10.0.0.77" not in json.dumps(dump)
