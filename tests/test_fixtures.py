"""The fixtures are the ground truth for every later test, so they get tested themselves.

Two things are being guarded here. The first is that the three MSO documents really do differ
in the ways the mirror has to cope with — it is easy to write three fixtures that are quietly
the same shape, and then a suite that proves nothing about firmware skew.

The second is privacy. A real `mso` document carries the owner's unit name, input labels, Dirac
slot names and serial number: that is site data, and this repository is public. These fixtures
were written from the documented schema rather than captured from a device, and
`test_fixtures_carry_no_site_data` is what keeps a future "let me just paste a real capture in"
from going unnoticed.
"""

from __future__ import annotations

import pytest

# Every invented string in the fixtures is drawn from this vocabulary. A real capture would
# bring words that are not in it.
INVENTED_INPUT_LABELS = {
    "Media Player",
    "Game Console",
    "Turntable",
    "Television",
    "Streaming Box",
    "Test Bench",
    "Roon",
    "",
}
INVENTED_SLOT_NAMES = {
    "Reference",
    "Movie Night",
    "Music",
    "Late Night",
    "Calibration Test",
    "",
}
TEST_SERIAL_PREFIX = "TESTSN"


def test_all_three_documents_load(mso_modern, mso_legacy, mso_sparse):
    for doc in (mso_modern, mso_legacy, mso_sparse):
        assert isinstance(doc, dict)
        assert doc, "an empty fixture would make every test that reads it vacuous"


def test_modern_and_legacy_differ_in_firmware_shape(mso_modern, mso_legacy):
    """1.13.x has no video status block at all; 2.1.x does. This is the skew that matters."""
    assert "videostat" in mso_modern
    assert "videostat" not in mso_legacy

    # The volume key was renamed between the two families.
    assert "secondaryVolume" in mso_modern
    assert "secondVolume" in mso_legacy
    assert "secondaryVolume" not in mso_legacy

    assert mso_modern["versions"]["swVer"].startswith("V2.")
    assert mso_legacy["versions"]["swVer"].startswith("V1.")


def test_both_documents_carry_exactly_six_dirac_slots(mso_modern, mso_legacy):
    """`/cal/currentdiracslot` is a 0-based index into this array, so its length is load-bearing."""
    for doc in (mso_modern, mso_legacy):
        assert len(doc["cal"]["slots"]) == 6


def test_the_two_unnamed_slot_shapes_are_both_represented(mso_modern, mso_legacy):
    """An empty name and an absent `name` key are different code paths in the mirror.

    A fixture set that only covered one of them would let the other regress silently.
    """
    modern_names = [slot.get("name") for slot in mso_modern["cal"]["slots"]]
    assert "" in modern_names, "modern fixture must contain a slot named the empty string"

    legacy_slots = mso_legacy["cal"]["slots"]
    assert any("name" not in slot for slot in legacy_slots), (
        "legacy fixture must contain a slot with no `name` key at all"
    )


def test_modern_carries_a_status_raw_blob_that_must_be_ignored(mso_modern):
    """`/status/raw` is decoder internals. The mirror must never walk it, so it must exist."""
    assert isinstance(mso_modern["status"]["raw"], dict)
    assert mso_modern["status"]["raw"], "an empty blob would not exercise the skip path"


def test_modern_carries_duplicate_input_labels(mso_modern):
    """Two visible inputs sharing a label is real, and the source list has to disambiguate."""
    labels = [
        info["label"]
        for info in mso_modern["inputs"].values()
        if info.get("visible") and info.get("label")
    ]
    assert len(labels) != len(set(labels)), "need at least one duplicated visible label"


def test_modern_carries_a_visible_input_with_a_blank_label(mso_modern):
    """A blank label must fall back to a built-in default rather than rendering as empty."""
    assert any(
        info.get("visible") and not info.get("label") for info in mso_modern["inputs"].values()
    )


def test_sparse_is_genuinely_sparse(mso_sparse):
    """The absence-tolerance fixture. If it grows keys, it stops testing anything."""
    assert set(mso_sparse) == {"volume", "powerIsOn"}


def test_wire_samples_cover_every_shape_the_unit_can_emit(wire_samples):
    required = {
        "get_mso",
        "mso_document",
        "msoupdate_array",
        "msoupdate_single_unwrapped_op",
        "bare_json_document",
        "bare_json_op_array",
        "bare_json_single_op",
        "error_bad_verb",
        "verb_with_no_argument",
        "value_containing_spaces",
        "empty_string",
        "null_argument",
        "invalid_json_argument",
        "unknown_verb",
        "status_raw_push",
    }
    missing = required - set(wire_samples)
    assert not missing, f"wire_samples is missing: {sorted(missing)}"


def test_wire_samples_include_a_container_replace_for_every_container_path(wire_samples):
    """All eight container paths send whole-subobject replaces, and each re-derives its leaves."""
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
    covered = {op["path"] for sample in wire_samples["container_replaces"] for op in sample["ops"]}
    assert expected <= covered, f"uncovered container paths: {sorted(expected - covered)}"


@pytest.mark.parametrize("fixture_name", ["mso_modern", "mso_legacy"])
def test_fixtures_carry_no_site_data(fixture_name, request):
    """These documents must be invented, never captured. This repository is public.

    A real `mso` carries the owner's unit name, input labels, Dirac slot names and serial.
    """
    doc = request.getfixturevalue(fixture_name)

    for key, info in doc.get("inputs", {}).items():
        assert info.get("label", "") in INVENTED_INPUT_LABELS, (
            f"input {key!r} has label {info.get('label')!r}, which is not an invented value"
        )

    for index, slot in enumerate(doc["cal"]["slots"]):
        assert slot.get("name", "") in INVENTED_SLOT_NAMES, (
            f"Dirac slot {index} has name {slot.get('name')!r}, which is not an invented value"
        )

    assert doc["versions"]["SerialNumber"].startswith(TEST_SERIAL_PREFIX)
    assert "Test" in doc["unitname"] or "Lab" in doc["unitname"]
