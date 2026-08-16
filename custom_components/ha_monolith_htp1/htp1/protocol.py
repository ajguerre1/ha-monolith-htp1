"""The HTP-1 wire codec. Pure: no I/O, no state, no clock.

Frames are text, formatted `verb[space]JSON`. Everything peculiar about that lives here, so
that the client above can be about sockets and timers rather than about string handling.

Two rules are worth stating out loud because both look like details and neither is:

1. **Split on the first space only.** `text.split()` would truncate any payload containing a
   space, which includes every document carrying a unit name.
2. **`changemso` never carries an empty array.** The unit rejects it, so "nothing to say" must
   be caught before it becomes a protocol error against a live processor.

`parse_message` never raises. A device we do not control is on the other end and an exception
here would drop the connection. Undecodable input is a return value.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

VERB_GET_MSO = "getmso"
VERB_MSO = "mso"
VERB_CHANGE_MSO = "changemso"
VERB_MSO_UPDATE = "msoupdate"
VERB_ERROR = "error"

OP_REPLACE = "replace"

# Top-level keys that mark a payload as a full document when it arrives with no verb, which
# newer firmware sometimes does. Any one of them is enough; a real document has most.
_DOCUMENT_MARKERS = frozenset(
    {
        "bassenhance",
        "cal",
        "input",
        "inputs",
        "loudness",
        "muted",
        "night",
        "powerAction",
        "powerIsOn",
        "status",
        "unitname",
        "upmix",
        "versions",
        "videostat",
        "volume",
    }
)


class MessageKind(StrEnum):
    """What arrived, and — for the two failure kinds — what the client should do about it.

    `MALFORMED` and `UNKNOWN` are deliberately separate. `MALFORMED` means we could not decode
    something we should have been able to decode, and it counts against the parse-failure
    budget. `UNKNOWN` means it decoded cleanly and we simply do not act on it, which must be
    free: newer firmware emits shapes this client has never seen, and throttling a healthy
    connection because of them would be a bug.
    """

    DOCUMENT = "document"
    UPDATE = "update"
    ERROR = "error"
    UNKNOWN = "unknown"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    """One decoded frame. Only the fields relevant to `kind` are populated."""

    kind: MessageKind
    verb: str | None = None
    document: dict[str, Any] | None = None
    ops: tuple[dict[str, Any], ...] = ()
    detail: str | None = None


def _is_operation(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("op"), str)
        and isinstance(value.get("path"), str)
    )


def normalise_ops(value: Any) -> tuple[dict[str, Any], ...] | None:
    """Coerce an update argument into a tuple of operations, or None if it is not operations.

    Accepts both shapes the unit uses: an array, and — sometimes — a single unwrapped
    operation. An empty array is operations, just none of them.
    """
    if _is_operation(value):
        return (value,)
    if isinstance(value, list):
        if all(_is_operation(item) for item in value):
            return tuple(value)
        return None
    return None


def classify_bare(value: Any) -> ParsedMessage:
    """Classify a payload that arrived with no verb at all.

    Reported on newer firmware. Anything unrecognised is `UNKNOWN`, never `MALFORMED` — it
    decoded, so it must not spend parse budget.
    """
    ops = normalise_ops(value)
    if ops:
        return ParsedMessage(kind=MessageKind.UPDATE, ops=ops)
    if isinstance(value, dict) and _DOCUMENT_MARKERS & value.keys():
        return ParsedMessage(kind=MessageKind.DOCUMENT, document=value)
    return ParsedMessage(kind=MessageKind.UNKNOWN)


def parse_message(text: str) -> ParsedMessage:
    """Decode one text frame. Never raises."""
    if not isinstance(text, str) or not text.strip():
        return ParsedMessage(kind=MessageKind.UNKNOWN)

    # The first space, and only the first. A unit name with a space in it must survive.
    verb, _, payload = text.strip().partition(" ")
    payload = payload.strip()

    if verb == VERB_MSO:
        decoded, ok = _decode(payload)
        if ok and isinstance(decoded, dict):
            return ParsedMessage(kind=MessageKind.DOCUMENT, verb=verb, document=decoded)
        return ParsedMessage(
            kind=MessageKind.MALFORMED, verb=verb, detail="mso argument is not an object"
        )

    if verb == VERB_MSO_UPDATE:
        decoded, ok = _decode(payload)
        if ok:
            ops = normalise_ops(decoded)
            if ops is not None:
                return ParsedMessage(kind=MessageKind.UPDATE, verb=verb, ops=ops)
        return ParsedMessage(
            kind=MessageKind.MALFORMED, verb=verb, detail="msoupdate argument is not operations"
        )

    if verb == VERB_ERROR:
        decoded, ok = _decode(payload)
        detail = decoded if ok and isinstance(decoded, str) else (payload or None)
        return ParsedMessage(kind=MessageKind.ERROR, verb=verb, detail=detail)

    # No verb we act on. It may still be a bare JSON payload, which newer firmware sends.
    decoded, ok = _decode(text.strip())
    if ok:
        bare = classify_bare(decoded)
        return ParsedMessage(
            kind=bare.kind, verb=None, document=bare.document, ops=bare.ops, detail=bare.detail
        )

    # Not our verb and not JSON. Ignorable, and specifically not a parse failure: the unit is
    # allowed to say things this client has never heard of.
    return ParsedMessage(kind=MessageKind.UNKNOWN, verb=verb or None)


def _decode(payload: str) -> tuple[Any, bool]:
    """`json.loads` with the exception folded into the return value."""
    if not payload:
        return None, False
    try:
        return json.loads(payload), True
    except (ValueError, TypeError):
        return None, False


def encode_get_mso() -> str:
    """The full-state request. Sent on every connect, and as the recovery path."""
    return VERB_GET_MSO


def replace_op(path: str, value: Any) -> dict[str, Any]:
    """One RFC 6902 `replace`. The only operation this client ever emits."""
    return {"op": OP_REPLACE, "path": path, "value": value}


def encode_change(ops: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> str:
    """Encode one `changemso`, or raise rather than send something the unit will reject.

    Refusing an empty list is not defensive programming for its own sake: the caller that
    reaches here with nothing to say has a bug, and sending `[]` would turn that into a
    protocol error against a live processor.

    `replace` only. A stored `test` operation replayed as a `replace` would *execute* rather
    than check, and an `add` against a member the unit does not have makes it reject the entire
    message — so one stray operation silently voids every other write in the same flush.
    """
    ops = list(ops)
    if not ops:
        raise ValueError(
            "changemso requires at least one operation; refusing to send an empty array"
        )
    for op in ops:
        if op.get("op") != OP_REPLACE:
            raise ValueError(f"only {OP_REPLACE!r} operations may be sent, got {op.get('op')!r}")
    return f"{VERB_CHANGE_MSO} {json.dumps(ops, separators=(',', ':'))}"
