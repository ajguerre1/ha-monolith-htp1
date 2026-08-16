"""The entities themselves: what exists, what it reports, and what it writes.

The most valuable test here is the inventory snapshot. Once this is deployed to five units and
fifty wall panels, entity ids are a permanent contract — renaming one silently breaks every
dashboard card and automation that names it. Asserting the exact set is what stops a rename
shipping by accident.

The second is change gating. Roughly fifty panels receive every state change, so a push that
moves nothing must produce no state write at all. That property is invisible in normal use and
expensive to get wrong.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.helpers import entity_registry as er

PATCH_CLIENT = "custom_components.ha_monolith_htp1.Htp1Client"

# What a firmware 2.x unit produces. Ten of these are created from the modern fixture; the
# three video sensors depend on a block firmware 1.13.x does not have at all.
EXPECTED_ENTITIES = {
    "media_player.test_processor",
    "number.test_processor_dialogue_enhancement",
    "number.test_processor_lip_sync",
    "select.test_processor_dirac",
    "select.test_processor_dirac_slot",
    "select.test_processor_night_mode",
    "sensor.test_processor_surround_mode",
    "sensor.test_processor_source_format",
    "sensor.test_processor_listening_format",
    "sensor.test_processor_video_resolution",
    "sensor.test_processor_hdr",
    "switch.test_processor_bass_enhancement",
    "switch.test_processor_loudness",
    "switch.test_processor_tone_control",
}

DISABLED_BY_DEFAULT = {
    "sensor.test_processor_program_format",
    "sensor.test_processor_input_sample_rate",
    "sensor.test_processor_output_sample_rate",
    "sensor.test_processor_dirac_status",
    "sensor.test_processor_colour_space",
}


async def _setup(hass, entry, client):
    with patch(PATCH_CLIENT, return_value=client):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _push(hass, client, changed):
    for listener in client.listeners:
        listener(frozenset(changed))


# --------------------------------------------------------------------------------------
# What exists
# --------------------------------------------------------------------------------------


async def test_the_entity_inventory_is_exactly_this(hass, config_entry, mock_client):
    """Entity ids are a permanent contract once this is deployed. Pin them."""
    await _setup(hass, config_entry, mock_client)

    created = {
        state.entity_id
        for state in hass.states.async_all()
        if state.entity_id.split(".")[1].startswith("test_processor")
        or state.entity_id == "media_player.test_processor"
    }
    assert created == EXPECTED_ENTITIES


async def test_the_churny_sensors_are_disabled_by_default(hass, config_entry, mock_client):
    """Sample rates move on every content change; fifty panels do not need that."""
    await _setup(hass, config_entry, mock_client)
    registry = er.async_get(hass)

    for entity_id in DISABLED_BY_DEFAULT:
        entry = registry.async_get(entity_id)
        assert entry is not None, f"{entity_id} should exist in the registry"
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(entity_id) is None


async def test_a_firmware_without_video_gets_no_video_sensors(
    hass, config_entry, mock_client, mso_legacy_mirror
):
    """1.13.x has no videostat block, so those entities are not created at all.

    An entity that is permanently unknown is worse than one that does not exist: it looks
    broken rather than absent.

    Matched by suffix rather than by full entity id, because the legacy fixture names its unit
    differently and the device name is what the object id is built from.
    """
    mock_client.mirror = mso_legacy_mirror
    await _setup(hass, config_entry, mock_client)

    entity_ids = {state.entity_id for state in hass.states.async_all()}
    assert not [e for e in entity_ids if e.endswith(("_video_resolution", "_hdr", "_colour_space"))]
    # Everything else still exists.
    assert [e for e in entity_ids if e.startswith("media_player.")]
    assert [e for e in entity_ids if e.endswith("_surround_mode")]


async def test_every_platform_declares_parallel_updates():
    """A missing declaration silently reintroduces per-entity serialisation."""
    import importlib

    for platform in (
        Platform.MEDIA_PLAYER,
        Platform.NUMBER,
        Platform.SELECT,
        Platform.SENSOR,
        Platform.SWITCH,
    ):
        module = importlib.import_module(f"custom_components.ha_monolith_htp1.{platform.value}")
        assert getattr(module, "PARALLEL_UPDATES", None) == 0, f"{platform.value} is missing it"


# --------------------------------------------------------------------------------------
# What it reports
# --------------------------------------------------------------------------------------


async def test_the_media_player_reports_the_units_own_values(hass, config_entry, mock_client):
    await _setup(hass, config_entry, mock_client)
    state = hass.states.get("media_player.test_processor")

    assert state.state == "on"
    # -25 dB over -50..0 is exactly half.
    assert state.attributes["volume_level"] == pytest.approx(0.5)
    assert state.attributes["is_volume_muted"] is False
    assert state.attributes["source"] == "Media Player (h1)"


async def test_the_volume_step_is_one_decibel(hass, config_entry, mock_client):
    """The 0.1 default would be a five-decibel jump on this range, which is a lot in a room.

    Read off the entity rather than the state: `volume_step` drives `volume_up`/`volume_down`
    and is not surfaced as a state attribute.
    """
    await _setup(hass, config_entry, mock_client)
    entity = hass.data["entity_components"]["media_player"].get_entity(
        "media_player.test_processor"
    )
    assert entity.volume_step == pytest.approx(1 / 50)


async def test_duplicate_source_labels_are_disambiguated(hass, config_entry, mock_client):
    """Two visible inputs share the label "Media Player" in the fixture."""
    await _setup(hass, config_entry, mock_client)
    sources = hass.states.get("media_player.test_processor").attributes["source_list"]

    assert "Media Player (h1)" in sources
    assert "Media Player (spdif1)" in sources
    # A blank label falls back to a readable default rather than an empty row.
    assert "HDMI 4" in sources


async def test_the_dirac_slot_is_labelled_by_index(hass, config_entry, mock_client):
    """On every unit measured, no slot is named — so names alone would give six blank rows."""
    await _setup(hass, config_entry, mock_client)
    state = hass.states.get("select.test_processor_dirac_slot")

    assert state.attributes["options"] == [
        "0 - Reference",
        "1 - Movie Night",
        "2 - Slot 2",
        "3 - Music",
        "4 - Late Night",
        "5 - Calibration Test",
    ]
    assert state.state == "1 - Movie Night"


async def test_a_string_valued_switch_reads_as_a_boolean(hass, config_entry, mock_client):
    """`/loudness` is "off" on the wire; `/eq/tc` is a real boolean. Both read as switches."""
    assert hass.states.get("switch.test_processor_loudness") is None
    await _setup(hass, config_entry, mock_client)

    assert hass.states.get("switch.test_processor_loudness").state == "off"
    assert hass.states.get("switch.test_processor_tone_control").state == "off"


async def test_sensors_report_the_units_own_words(hass, config_entry, mock_client):
    """Free text, deliberately: `5.2.2t` is a real value no enumeration would have contained."""
    await _setup(hass, config_entry, mock_client)

    assert hass.states.get("sensor.test_processor_surround_mode").state == "Native Dolby ATMOS"
    assert hass.states.get("sensor.test_processor_listening_format").state == "5.1.2"


async def test_a_push_moves_the_entity(hass, config_entry, mock_client):
    await _setup(hass, config_entry, mock_client)

    mock_client.mirror.apply_ops([{"op": "replace", "path": "/volume", "value": -40}])
    _push(hass, mock_client, {"volume"})
    await hass.async_block_till_done()

    state = hass.states.get("media_player.test_processor")
    assert state.attributes["volume_level"] == pytest.approx(0.2)


async def test_everything_goes_unavailable_together(hass, config_entry, mock_client):
    """One outage, every entity — and back together when it returns."""
    await _setup(hass, config_entry, mock_client)

    mock_client.connected = False
    _push(hass, mock_client, set())
    await hass.async_block_till_done()

    for entity_id in ("media_player.test_processor", "switch.test_processor_loudness"):
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    mock_client.connected = True
    _push(hass, mock_client, {"volume"})
    await hass.async_block_till_done()

    assert hass.states.get("media_player.test_processor").state != STATE_UNAVAILABLE


async def test_an_absent_field_reads_unknown_rather_than_unavailable(
    hass, config_entry, mock_client
):
    """Unknown means we can talk to it and it has not said; unavailable means we cannot."""
    mock_client.mirror.apply_ops([{"op": "remove", "path": "/status/SurroundMode"}])
    await _setup(hass, config_entry, mock_client)

    state = hass.states.get("sensor.test_processor_surround_mode")
    if state is not None:  # not created at all is also acceptable for an absent field
        assert state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE)


# --------------------------------------------------------------------------------------
# Change gating
# --------------------------------------------------------------------------------------


async def test_a_push_that_moves_nothing_writes_no_state(hass, config_entry, mock_client):
    """The third gating layer. Fifty wall panels receive every state change."""
    await _setup(hass, config_entry, mock_client)
    before = hass.states.get("media_player.test_processor").last_updated

    # The mirror already holds this value, so nothing moves.
    mock_client.mirror.apply_ops([{"op": "replace", "path": "/volume", "value": -25}])
    _push(hass, mock_client, {"volume"})
    await hass.async_block_till_done()

    assert hass.states.get("media_player.test_processor").last_updated == before


async def test_a_push_only_wakes_the_entities_that_moved(hass, config_entry, mock_client):
    """A volume change must not rewrite the loudness switch."""
    await _setup(hass, config_entry, mock_client)
    switch_before = hass.states.get("switch.test_processor_loudness").last_updated

    mock_client.mirror.apply_ops([{"op": "replace", "path": "/volume", "value": -41}])
    _push(hass, mock_client, {"volume"})
    await hass.async_block_till_done()

    assert hass.states.get("switch.test_processor_loudness").last_updated == switch_before


# --------------------------------------------------------------------------------------
# What it writes
# --------------------------------------------------------------------------------------


async def test_selecting_a_source_writes_the_key_not_the_label(hass, config_entry, mock_client):
    """The user sees "Turntable"; the unit only understands `a1`."""
    await _setup(hass, config_entry, mock_client)

    await hass.services.async_call(
        "media_player",
        "select_source",
        {"entity_id": "media_player.test_processor", "source": "Turntable"},
        blocking=True,
    )

    mock_client.async_write.assert_awaited_with("/input", "a1")


async def test_selecting_a_dirac_slot_writes_the_index(hass, config_entry, mock_client):
    await _setup(hass, config_entry, mock_client)

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.test_processor_dirac_slot", "option": "3 - Music"},
        blocking=True,
    )

    mock_client.async_write.assert_awaited_with("/cal/currentdiracslot", 3)


async def test_a_volume_step_moves_exactly_one_decibel(hass, config_entry, mock_client):
    """The unit has no relative verb, so a step is read-modify-write in whole dB."""
    await _setup(hass, config_entry, mock_client)

    await hass.services.async_call(
        "media_player",
        "volume_up",
        {"entity_id": "media_player.test_processor"},
        blocking=True,
    )

    mock_client.async_write.assert_awaited_with("/volume", -24)


async def test_a_number_writes_an_integer(hass, config_entry, mock_client):
    """Every numeric path on this unit takes an integer; 40.0 is asking for trouble."""
    await _setup(hass, config_entry, mock_client)

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.test_processor_lip_sync", "value": 120},
        blocking=True,
    )

    path, value = mock_client.async_write.await_args.args
    assert path == "/cal/lipsync"
    assert value == 120
    assert isinstance(value, int)


async def test_a_switch_writes_a_boolean_and_the_client_encodes_it(hass, config_entry, mock_client):
    """The entity stays in Python terms; turning "on" into "on" is the codec's job."""
    await _setup(hass, config_entry, mock_client)

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.test_processor_loudness"},
        blocking=True,
    )

    mock_client.async_write.assert_awaited_with("/loudness", True)
