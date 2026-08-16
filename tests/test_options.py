"""Building the dropdown lists: sources, sound modes and Dirac slots.

These are pure functions, and they are where a frontend renders a blank row or a user picks the
wrong calibration. Three rules earn their tests:

**Order is canonical, never dictionary order.** JSON object order is not a contract, so a unit
that reorders its `/inputs` map between documents would otherwise reshuffle every dropdown in
the house on reconnect.

**The current value is always in the list.** Home Assistant renders a blank selector when the
reported value is absent from the option list, and an input can legitimately be selected while
invisible.

**Duplicate labels disambiguate every colliding member, not just the later one.** Suffixing only
the second occurrence makes the result depend on iteration order, which is the thing the first
rule is trying to remove.
"""

from __future__ import annotations

import pytest

from custom_components.ha_monolith_htp1.htp1.models import DiracSlot, InputInfo
from custom_components.ha_monolith_htp1.htp1.options import (
    dirac_slot_options,
    sound_mode_options,
    source_options,
)


def _inputs(**spec: tuple[str, bool]) -> dict[str, InputInfo]:
    return {key: InputInfo(key=key, label=label, visible=vis) for key, (label, vis) in spec.items()}


# --------------------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------------------


def test_only_visible_inputs_are_offered():
    options = source_options(_inputs(h1=("Media Player", True), h2=("Hidden", False)))
    assert list(options) == ["Media Player"]


def test_a_blank_label_falls_back_to_a_readable_default():
    """Otherwise the dropdown shows an empty row the user cannot identify."""
    options = source_options(_inputs(h4=("", True), spdif2=("", True), b=("", True)))
    assert list(options) == ["HDMI 4", "Coax 2", "Bluetooth"]


def test_duplicate_labels_are_disambiguated_on_every_collision():
    """Suffixing only the second occurrence would make the result order-dependent."""
    options = source_options(_inputs(h1=("Media Player", True), spdif1=("Media Player", True)))
    assert list(options) == ["Media Player (h1)", "Media Player (spdif1)"]
    assert options["Media Player (h1)"] == "h1"
    assert options["Media Player (spdif1)"] == "spdif1"


def test_a_label_that_is_unique_is_left_alone():
    options = source_options(_inputs(h1=("Media Player", True), a1=("Turntable", True)))
    assert list(options) == ["Media Player", "Turntable"]


def test_the_order_is_canonical_not_dictionary_order():
    """A unit that reorders its inputs map must not reshuffle every dropdown in the house."""
    forward = source_options(
        _inputs(h1=("One", True), a1=("Two", True), tv=("Three", True), roon=("Four", True))
    )
    shuffled = source_options(
        _inputs(roon=("Four", True), tv=("Three", True), a1=("Two", True), h1=("One", True))
    )
    assert list(forward) == list(shuffled) == ["One", "Two", "Three", "Four"]


def test_the_current_input_is_offered_even_when_invisible():
    """`source` must always appear in `source_list`, or the frontend renders blank."""
    inputs = _inputs(h1=("Media Player", True), h7=("Service", False))
    options = source_options(inputs, current="h7")
    assert "Service" in options
    assert options["Service"] == "h7"


def test_the_current_input_is_offered_even_when_absent_from_the_document():
    options = source_options(_inputs(h1=("Media Player", True)), current="usb")
    assert options["USB Audio"] == "usb"


def test_an_unknown_input_key_still_gets_a_label():
    options = source_options({"zz9": InputInfo(key="zz9", label="", visible=True)})
    assert list(options) == ["ZZ9"]


def test_no_inputs_at_all_is_an_empty_list_not_an_error():
    assert source_options({}) == {}


# --------------------------------------------------------------------------------------
# Sound modes
# --------------------------------------------------------------------------------------


def test_a_mode_the_unit_hides_is_not_offered():
    """Only an explicit `homevis: false` hides a mode. See the rule below."""
    visibility = {
        "off": True,
        "native": True,
        "dolby": True,
        "dts": True,
        "auro": False,
        "mono": False,
        "stereo": False,
    }
    options = sound_mode_options(visibility)
    assert list(options) == ["Direct", "Native", "Dolby Surround", "DTS Neural:X"]


def test_a_mode_with_no_visibility_flag_is_shown():
    """The rule: absent means visible, never hidden.

    Firmware 1.13.x omits `homevis`, and there is no way to distinguish "this firmware does not
    report visibility" from "this mode is hidden". Defaulting to hidden would empty the whole
    dropdown on that firmware; defaulting to visible costs at worst an extra entry.
    """
    assert "Dolby Surround" in sound_mode_options({})
    assert len(sound_mode_options({})) == 7


def test_sound_mode_order_is_canonical():
    """Order follows the unit's own interface, not the order the flags happened to arrive in."""
    shuffled = sound_mode_options({"stereo": True, "dolby": True, "off": True})
    assert list(shuffled)[:3] == ["Direct", "Native", "Dolby Surround"]
    assert list(shuffled)[-1] == "Stereo"


def test_the_current_sound_mode_is_offered_even_when_hidden():
    options = sound_mode_options({"auro": False}, current="auro")
    assert options["Auro-3D"] == "auro"


def test_sound_mode_labels_map_back_to_wire_keys():
    options = sound_mode_options({"dts": True})
    assert options["DTS Neural:X"] == "dts"


# --------------------------------------------------------------------------------------
# Dirac slots
# --------------------------------------------------------------------------------------


def _slots(*names: str) -> list[DiracSlot]:
    return [DiracSlot(index=i, name=name) for i, name in enumerate(names)]


def test_every_slot_is_offered_with_its_wire_index():
    """The number the user sees is the number `/cal/currentdiracslot` uses."""
    options = dirac_slot_options(_slots("Reference", "Movie Night", "", "Music", "", "Test"))
    assert list(options) == [
        "0 - Reference",
        "1 - Movie Night",
        "2 - Slot 2",
        "3 - Music",
        "4 - Slot 4",
        "5 - Test",
    ]
    assert options["3 - Music"] == 3


def test_duplicate_slot_names_stay_unique_for_free():
    """The index prefix does the disambiguation, so identical names cannot collide."""
    options = dirac_slot_options(_slots("Music", "Music", "Music", "Music", "Music", "Music"))
    assert len(options) == 6


@pytest.mark.parametrize("index", [0, 3, 5])
def test_the_current_slot_resolves_by_position_not_by_name(index):
    slots = _slots("Music", "Music", "Music", "Music", "Music", "Music")
    options = dirac_slot_options(slots)
    label = next(lbl for lbl, value in options.items() if value == index)
    assert label.startswith(f"{index} - ")


def test_an_out_of_range_current_slot_reports_nothing_rather_than_the_wrong_one():
    """Reporting a wrong calibration is worse than reporting none."""
    options = dirac_slot_options(_slots("A", "B", "C", "D", "E", "F"))
    assert 9 not in options.values()
