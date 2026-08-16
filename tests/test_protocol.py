"""The wire codec: `verb[space]JSON` in, structured message out.

Every quirk of this protocol lives in `protocol.py` and nowhere else, so this is where they get
pinned. Two are load-bearing and easy to "simplify" away:

- **Split on the FIRST space only.** `text.split()` looks equivalent and is not: a document
  containing a unit name with spaces in it would be truncated.
- **`changemso` must never carry an empty op array.** The unit rejects it, and an encoder that
  happily emits `[]` turns "nothing to say" into a protocol error against a live processor.

The other theme is that `parse_message` must never raise. It sits directly on bytes from a
device we do not control, and an exception there becomes a dropped connection. Undecodable
input is a *return value*, and it is deliberately distinct from decodable-but-unrecognised
input: the first counts against the parse-failure budget, the second is ignored. Conflating
them would either throttle a healthy connection or fail to throttle a sick one.
"""

from __future__ import annotations

import json

import pytest

from custom_components.ha_monolith_htp1.htp1 import protocol
from custom_components.ha_monolith_htp1.htp1.protocol import MessageKind

# --------------------------------------------------------------------------------------
# Framing
# --------------------------------------------------------------------------------------


def test_a_payload_containing_spaces_is_not_split_further(wire_samples):
    """`split()` would truncate this. `split(" ", 1)` is the contract."""
    parsed = protocol.parse_message(wire_samples["value_containing_spaces"])
    assert parsed.kind is MessageKind.DOCUMENT
    assert parsed.document["unitname"] == "Test Processor Two"


def test_a_verb_with_no_argument_parses(wire_samples):
    parsed = protocol.parse_message(wire_samples["verb_with_no_argument"])
    assert parsed.kind is MessageKind.UNKNOWN
    assert parsed.verb == "getmso"


def test_a_document_is_recognised(wire_samples):
    parsed = protocol.parse_message(wire_samples["mso_document"])
    assert parsed.kind is MessageKind.DOCUMENT
    assert parsed.document["volume"] == -25
    assert parsed.document["muted"] is False


def test_an_update_carries_its_operations(wire_samples):
    parsed = protocol.parse_message(wire_samples["msoupdate_array"])
    assert parsed.kind is MessageKind.UPDATE
    assert parsed.ops == ({"op": "replace", "path": "/volume", "value": -30},)


def test_multiple_operations_survive_in_order(wire_samples):
    parsed = protocol.parse_message(wire_samples["msoupdate_multi_op"])
    assert [op["path"] for op in parsed.ops] == ["/volume", "/muted"]


def test_a_single_unwrapped_operation_is_accepted(wire_samples):
    """The unit sometimes sends one bare op instead of a one-element array."""
    parsed = protocol.parse_message(wire_samples["msoupdate_single_unwrapped_op"])
    assert parsed.kind is MessageKind.UPDATE
    assert parsed.ops == ({"op": "replace", "path": "/volume", "value": -30},)


def test_an_untracked_path_still_parses(wire_samples):
    """Filtering is the mirror's job. The codec reports what arrived."""
    parsed = protocol.parse_message(wire_samples["status_raw_push"])
    assert parsed.kind is MessageKind.UPDATE
    assert parsed.ops[0]["path"] == "/status/raw/activityMask"


# --------------------------------------------------------------------------------------
# Errors and things we do not recognise
# --------------------------------------------------------------------------------------


def test_error_frames_are_recognised_and_survivable(wire_samples):
    """Junk input yields `error "bad-verb"` and the connection stays up."""
    parsed = protocol.parse_message(wire_samples["error_bad_verb"])
    assert parsed.kind is MessageKind.ERROR
    assert parsed.detail == "bad-verb"


def test_an_unknown_verb_is_unknown_not_malformed(wire_samples):
    """It decoded fine; we simply do not act on it. It must not spend parse budget."""
    parsed = protocol.parse_message(wire_samples["unknown_verb"])
    assert parsed.kind is MessageKind.UNKNOWN


def test_undecodable_input_is_malformed(wire_samples):
    """This is the one that counts against the budget."""
    parsed = protocol.parse_message(wire_samples["invalid_json_argument"])
    assert parsed.kind is MessageKind.MALFORMED
    assert parsed.detail


@pytest.mark.parametrize(
    "sample_key",
    ["empty_string", "only_a_space", "lone_bracket"],
)
def test_degenerate_frames_never_raise(wire_samples, sample_key):
    assert protocol.parse_message(wire_samples[sample_key]) is not None


def test_parse_never_raises():
    """A device we do not control is on the other end; an exception here drops the link."""
    hostile = [
        "",
        " ",
        "  ",
        "mso",
        "mso ",
        "mso {",
        "mso {}",
        "mso []",
        "mso null",
        "mso 42",
        'mso "a string"',
        "mso true",
        "msoupdate",
        "msoupdate ",
        "msoupdate {",
        "msoupdate []",
        "msoupdate null",
        "msoupdate 42",
        "msoupdate [1,2,3]",
        'msoupdate [{"nope": 1}]',
        'msoupdate {"op":"replace"}',
        'msoupdate {"path":"/volume"}',
        "error",
        "error ",
        "error null",
        "error {}",
        "[",
        "]",
        "{",
        "}",
        "{}",
        "[]",
        "null",
        "42",
        "true",
        '"bare string"',
        "\n",
        "\t",
        "\x00",
        "getmso extra argument here",
        "a" * 10000,
        "🎛️",
    ]
    for text in hostile:
        parsed = protocol.parse_message(text)
        assert parsed.kind in set(MessageKind), f"unexpected kind for {text!r}"


# --------------------------------------------------------------------------------------
# Bare JSON (newer firmware sends payloads with no verb at all)
# --------------------------------------------------------------------------------------


def test_bare_json_document_is_recognised(wire_samples):
    parsed = protocol.parse_message(wire_samples["bare_json_document"])
    assert parsed.kind is MessageKind.DOCUMENT
    assert parsed.document["unitname"] == "Test Processor"


def test_bare_json_operation_array_is_recognised(wire_samples):
    parsed = protocol.parse_message(wire_samples["bare_json_op_array"])
    assert parsed.kind is MessageKind.UPDATE
    assert parsed.ops[0]["path"] == "/muted"


def test_bare_json_single_operation_is_recognised(wire_samples):
    parsed = protocol.parse_message(wire_samples["bare_json_single_op"])
    assert parsed.kind is MessageKind.UPDATE
    assert parsed.ops[0]["path"] == "/muted"


def test_bare_json_we_do_not_recognise_is_unknown_not_malformed(wire_samples):
    """Decoded cleanly, shape unrecognised. Dropping it is correct; throttling for it is not."""
    parsed = protocol.parse_message(wire_samples["bare_json_unrecognised"])
    assert parsed.kind is MessageKind.UNKNOWN


# --------------------------------------------------------------------------------------
# Encoding
# --------------------------------------------------------------------------------------


def test_get_mso_is_a_bare_verb():
    assert protocol.encode_get_mso() == "getmso"


def test_encode_change_produces_one_message_with_all_operations():
    text = protocol.encode_change(
        [protocol.replace_op("/volume", -30), protocol.replace_op("/muted", True)]
    )
    verb, _, payload = text.partition(" ")
    assert verb == "changemso"
    ops = json.loads(payload)
    assert [op["path"] for op in ops] == ["/volume", "/muted"]
    assert all(op["op"] == "replace" for op in ops)


def test_encode_change_refuses_an_empty_operation_list():
    """An empty array is a protocol error at the unit, so it must never leave here."""
    with pytest.raises(ValueError):
        protocol.encode_change([])


def test_only_replace_operations_are_emitted():
    """A stored `test` op replayed as a `replace` would execute, not check.

    An `add` against a member the unit does not have makes it reject the whole message.
    """
    with pytest.raises(ValueError):
        protocol.encode_change([{"op": "add", "path": "/inputs/h8/label", "value": "x"}])


def test_encoded_messages_are_split_on_the_first_space_by_our_own_parser():
    """Round-trip: whatever we encode, our parser must read back identically."""
    text = protocol.encode_change([protocol.replace_op("/unitname", "Test Processor Two")])
    verb, _, payload = text.partition(" ")
    assert verb == "changemso"
    assert json.loads(payload)[0]["value"] == "Test Processor Two"


# --------------------------------------------------------------------------------------
# normalise_ops
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ([{"op": "replace", "path": "/a", "value": 1}], 1),
        ({"op": "replace", "path": "/a", "value": 1}, 1),
        (
            [
                {"op": "replace", "path": "/a", "value": 1},
                {"op": "replace", "path": "/b", "value": 2},
            ],
            2,
        ),
        ([], 0),
    ],
)
def test_normalise_ops_accepts_both_shapes(value, expected):
    assert len(protocol.normalise_ops(value)) == expected


@pytest.mark.parametrize("value", [None, 42, "text", {}, {"nope": 1}, [1, 2], [{"nope": 1}]])
def test_normalise_ops_rejects_anything_that_is_not_operations(value):
    assert protocol.normalise_ops(value) is None
