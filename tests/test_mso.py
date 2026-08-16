"""The MSO mirror: a ~38 KB document projected down to the ~30 leaves this integration uses.

Three behaviours here are subtle enough that getting them wrong produces no error, just wrong
state, and all three are pinned below.

**Container replaces are real.** The unit sends `replace` on `/status`, `/cal`, `/inputs` and
five other subtrees, where the value is the whole sub-object. Every tracked leaf beneath has to
be re-derived from it, or the mirror keeps values the unit has already moved on from.

**Absent is unspecified, not cleared.** A partial `/inputs` replace naming three inputs must not
wipe the other eighteen. The single exception is a full document from `getmso`, which is a
census: what it omits is genuinely gone.

**`/cal/slots` always has six rows.** `/cal/currentdiracslot` is a 0-based index into that
array, so a slot with no name still occupies its position. Dropping unnamed slots would
misalign every slot after it and point the selector at the wrong calibration.

The change set is the fourth thing worth guarding: it must contain exactly the fields that
moved. The live Home Assistant fans every state change out to ~50 wall panels, so a mirror that
reports spurious changes is a performance defect, not a cosmetic one.
"""

from __future__ import annotations

import pytest

from custom_components.ha_monolith_htp1.htp1 import protocol
from custom_components.ha_monolith_htp1.htp1.mso import CONTAINER_PREFIXES, TRACKED_PATHS, MsoMirror


@pytest.fixture
def modern(mso_modern):
    mirror = MsoMirror()
    mirror.apply_document(mso_modern)
    return mirror


@pytest.fixture
def legacy(mso_legacy):
    mirror = MsoMirror()
    mirror.apply_document(mso_legacy)
    return mirror


def _container(wire_samples, path: str):
    """The container-replace sample for one subtree."""
    return next(s for s in wire_samples["container_replaces"] if s["ops"][0]["path"] == path)


def _ops(text: str):
    """Parse a wire sample down to its operations."""
    return protocol.parse_message(text).ops


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------


def test_a_fresh_mirror_is_not_loaded():
    assert MsoMirror().loaded is False


def test_the_three_fixtures_load_without_error(mso_modern, mso_legacy, mso_sparse):
    for doc in (mso_modern, mso_legacy, mso_sparse):
        mirror = MsoMirror()
        mirror.apply_document(doc)
        assert mirror.loaded is True


def test_a_modern_document_populates_the_fields_we_read(modern):
    assert modern.get("volume") == -25
    assert modern.get("muted") is False
    assert modern.get("power") is True
    assert modern.get("input") == "h1"
    assert modern.get("upmix") == "native"
    assert modern.get("vpl") == -50
    assert modern.get("vph") == 0
    assert modern.get("surround_mode") == "Native Dolby ATMOS"
    assert modern.get("video_resolution") == "3840x2160p60Hz"
    assert modern.get("serial") == "TESTSN0001"


def test_string_valued_switches_decode_to_booleans(modern):
    """`/loudness` and `/bassenhance` are the strings "on"/"off", not JSON booleans."""
    assert modern.get("loudness") is False
    assert modern.get("bass_enhance") is False


def test_version_strings_are_normalised(modern):
    assert modern.get("av_controller") == "5.96"
    assert modern.get("system_version") == "V2.1.1"


def test_a_sparse_document_loads_without_error(mso_sparse):
    """Absence tolerance, total. Two keys and nothing else must not raise."""
    mirror = MsoMirror()
    mirror.apply_document(mso_sparse)
    assert mirror.get("volume") == -10
    assert mirror.get("power") is False
    assert mirror.get("surround_mode") is None
    assert mirror.has("surround_mode") is False


def test_legacy_firmware_has_no_video_fields(legacy):
    """1.13.x carries no `videostat` block at all, and that must disable rather than raise."""
    assert legacy.has("video_resolution") is False
    assert legacy.get("video_resolution") is None
    assert legacy.get("volume") == -30


def test_the_legacy_volume_range_is_read_from_the_unit(legacy):
    """Anything that hardcodes -50..0 fails here, which is why the fixture differs."""
    assert legacy.get("vpl") == -60
    assert legacy.get("vph") == -5


# --------------------------------------------------------------------------------------
# Change sets
# --------------------------------------------------------------------------------------


def test_the_change_set_is_exactly_the_fields_that_moved(modern):
    changed = modern.apply_ops(_ops('msoupdate [{"op":"replace","path":"/volume","value":-30}]'))
    assert changed == frozenset({"volume"})
    assert modern.get("volume") == -30


def test_a_push_that_changes_nothing_notifies_nobody(modern):
    """First of the three change-gating layers. A no-op push must cost nothing upstream."""
    changed = modern.apply_ops(_ops('msoupdate [{"op":"replace","path":"/volume","value":-25}]'))
    assert changed == frozenset()


def test_multiple_moved_fields_all_appear(modern):
    changed = modern.apply_ops(
        _ops(
            'msoupdate [{"op":"replace","path":"/volume","value":-30},'
            '{"op":"replace","path":"/muted","value":true}]'
        )
    )
    assert changed == frozenset({"volume", "muted"})


def test_a_single_unwrapped_op_is_accepted(modern, wire_samples):
    changed = modern.apply_ops(_ops(wire_samples["msoupdate_single_unwrapped_op"]))
    assert changed == frozenset({"volume"})


def test_status_raw_is_never_walked(modern, wire_samples):
    """`/status/raw` is decoder internals; touching it would defeat the projection."""
    changed = modern.apply_ops(_ops(wire_samples["status_raw_push"]))
    assert changed == frozenset()


def test_unknown_paths_are_dropped_silently(modern, wire_samples):
    changed = modern.apply_ops(_ops(wire_samples["untracked_path_push"]))
    assert changed == frozenset()


def test_applying_nothing_is_harmless(modern):
    assert modern.apply_ops(()) == frozenset()
    assert modern.apply_ops(None) == frozenset()


# --------------------------------------------------------------------------------------
# Container replaces
# --------------------------------------------------------------------------------------


def test_every_container_path_is_declared():
    """The eight subtrees the unit is known to replace wholesale."""
    expected = {
        "/cal",
        "/cal/slots",
        "/inputs",
        "/status",
        "/svronly",
        "/upmix",
        "/versions",
        "/videostat",
    }
    assert set(CONTAINER_PREFIXES) == expected


def test_a_status_container_replace_rederives_every_leaf(modern, wire_samples):
    sample = _container(wire_samples, "/status")
    changed = modern.apply_ops(tuple(sample["ops"]))
    assert modern.get("surround_mode") == "Dolby Surround"
    assert modern.get("source_program") == "PCM"
    assert modern.get("input_sample_rate") == "44.1 kHz"
    assert modern.get("dirac_status") == "bypass"
    assert "surround_mode" in changed


def test_a_cal_container_replace_rederives_leaves_and_slots(modern, wire_samples):
    sample = _container(wire_samples, "/cal")
    modern.apply_ops(tuple(sample["ops"]))
    assert modern.get("vpl") == -60
    assert modern.get("vph") == -5
    assert modern.get("lip_sync") == 120
    assert modern.get("dirac_slot") == 4
    assert modern.get("dirac_active") == "bypass"
    assert len(modern.dirac_slots) == 6


def test_a_videostat_container_replace_rederives_every_leaf(modern, wire_samples):
    sample = _container(wire_samples, "/videostat")
    modern.apply_ops(tuple(sample["ops"]))
    assert modern.get("video_resolution") == "1920x1080p60Hz"
    assert modern.get("hdr_status") == "--"


def test_a_versions_container_replace_rederives_and_normalises(modern, wire_samples):
    sample = _container(wire_samples, "/versions")
    modern.apply_ops(tuple(sample["ops"]))
    assert modern.get("system_version") == "V2.1.2"
    assert modern.get("av_controller") == "5.97"


def test_an_upmix_container_replace_rederives_selection_and_visibility(modern, wire_samples):
    sample = _container(wire_samples, "/upmix")
    modern.apply_ops(tuple(sample["ops"]))
    assert modern.get("upmix") == "dts"
    assert modern.upmix_visible["native"] is False
    assert modern.upmix_visible["auro"] is True


def test_a_slots_container_replace_keeps_six_rows(modern, wire_samples):
    sample = _container(wire_samples, "/cal/slots")
    modern.apply_ops(tuple(sample["ops"]))
    assert len(modern.dirac_slots) == 6
    assert modern.dirac_slots[2].name == ""


def test_an_svronly_container_replace_does_not_raise(modern, wire_samples):
    """Untracked, but it arrives, and it must not take the mirror down."""
    sample = _container(wire_samples, "/svronly")
    assert modern.apply_ops(tuple(sample["ops"])) == frozenset()


def test_absent_keys_are_unspecified_not_cleared(modern, wire_samples):
    """A partial `/inputs` replace naming three inputs must not wipe the other eighteen."""
    before = modern.inputs["a1"].label
    sample = _container(wire_samples, "/inputs")
    modern.apply_ops(tuple(sample["ops"]))
    assert modern.inputs["h2"].label == "Test Bench", "the named input should have moved"
    assert modern.inputs["a1"].label == before, "an unnamed input must not be wiped"


# --------------------------------------------------------------------------------------
# Documents are a census
# --------------------------------------------------------------------------------------


def test_a_full_document_is_a_census(modern, mso_sparse):
    """The one place members may legitimately disappear."""
    assert modern.get("surround_mode") is not None
    modern.apply_document(mso_sparse)
    assert modern.get("surround_mode") is None
    assert modern.get("volume") == -10


# --------------------------------------------------------------------------------------
# Dirac slots
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name", ["modern", "legacy"])
def test_slots_are_always_six_rows(fixture_name, request):
    """Both unnamed shapes — `name: ""` and no `name` key — must still occupy a row."""
    mirror = request.getfixturevalue(fixture_name)
    assert len(mirror.dirac_slots) == 6
    assert [slot.index for slot in mirror.dirac_slots] == [0, 1, 2, 3, 4, 5]


def test_slot_indices_stay_aligned_with_currentdiracslot(modern):
    """`/cal/currentdiracslot` indexes this array, so position is the contract."""
    assert modern.get("dirac_slot") == 1
    assert modern.dirac_slots[1].name == "Movie Night"


def test_a_slot_with_no_name_key_survives_as_an_empty_name(legacy):
    assert legacy.dirac_slots[2].name == ""


def test_a_missing_slot_array_still_yields_six_rows(mso_sparse):
    mirror = MsoMirror()
    mirror.apply_document(mso_sparse)
    assert len(mirror.dirac_slots) == 6


# --------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------


def test_inputs_are_projected_with_labels_and_visibility(modern):
    assert modern.inputs["h1"].label == "Media Player"
    assert modern.inputs["h1"].visible is True
    assert modern.inputs["h5"].visible is False


def test_an_input_label_push_moves_only_that_input(modern, wire_samples):
    changed = modern.apply_ops(_ops(wire_samples["input_label_push"]))
    assert modern.inputs["h2"].label == "Streaming Box"
    assert modern.inputs["h1"].label == "Media Player"
    assert changed == frozenset({"inputs"})


def test_an_input_visibility_push_is_reported(modern, wire_samples):
    changed = modern.apply_ops(_ops(wire_samples["input_visible_push"]))
    assert modern.inputs["h3"].visible is False
    assert changed == frozenset({"inputs"})


# --------------------------------------------------------------------------------------
# Codec mismatch reporting (moved here from models: "report once" is state)
# --------------------------------------------------------------------------------------


def test_a_codec_mismatch_is_reported_once(modern):
    """`/eq/tc` is declared boolean but unmeasured on real firmware (HW-02).

    If a unit sends the other shape the value must still decode, and the mismatch must be
    reported exactly once rather than on every push for the life of the connection.
    """
    ops = _ops('msoupdate [{"op":"replace","path":"/eq/tc","value":"on"}]')
    modern.apply_ops(ops)
    assert modern.get("tone_control") is True
    assert modern.mismatches == ("/eq/tc",)

    modern.apply_ops(_ops('msoupdate [{"op":"replace","path":"/eq/tc","value":"off"}]'))
    assert modern.get("tone_control") is False
    assert modern.mismatches == ("/eq/tc",), "the mismatch must not be reported twice"


def test_a_matching_codec_reports_no_mismatch(modern):
    modern.apply_ops(_ops('msoupdate [{"op":"replace","path":"/eq/tc","value":true}]'))
    assert modern.mismatches == ()


# --------------------------------------------------------------------------------------
# The tracked path table
# --------------------------------------------------------------------------------------


def test_every_tracked_path_is_an_absolute_json_pointer():
    for path in TRACKED_PATHS:
        assert path.startswith("/"), f"{path!r} is not a JSON pointer"
        assert not path.endswith("/")


def test_field_names_are_unique():
    names = [field.name for field in TRACKED_PATHS.values()]
    assert len(names) == len(set(names))
