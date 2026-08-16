"""Value semantics for the HTP-1. Pure functions and value types; no I/O, no state.

The volume map is the part worth reading carefully.

The unit takes an **integer dB** clamped to `[cal.vpl, cal.vph]`, and both bounds are
user-configurable — never assume -50..0. Home Assistant takes a **float 0..1**. The conversion
between them is only interesting because of two decisions:

1. **The fraction is never quantised.** The Control4 driver for this same processor converts dB
   to an integer percentage, because a Control4 room endpoint takes one. Reusing that here is
   silently lossy: a range with more than 101 dB values cannot survive the round trip. Over
   -127..0 that is 27 of 128 values, and the first failure returns one dB *louder* than
   requested.
2. **Ties round down**, via `ceil(x - 0.5)`. Over -50..0, roughly half the round percentages a
   UI sends land exactly on a half-dB, so the tie rule decides most real inputs rather than an
   edge case. A volume control should land quieter than asked, never louder.

`round()` is wrong for this: Python rounds half to even, so 1.5 becomes 2 while 2.5 becomes 2,
and half of all ties would go up.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------------------
# Rounding and the volume map
# --------------------------------------------------------------------------------------


def round_half_down(value: float) -> int:
    """Round to the nearest whole number, sending exact ties downward.

    `ceil(x - 0.5)` states that directly and holds for either sign. Rounding half away from
    zero would look correct only because these dB values are usually negative; it would send a
    tie upward — louder — the moment a unit reported a positive ceiling.
    """
    return math.ceil(value - 0.5)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def db_to_fraction(db: float, vpl: float, vph: float) -> float:
    """Device dB to a Home Assistant `volume_level`, as an **unrounded** float in 0..1."""
    if vph <= vpl:
        # A unit reporting a nonsense range must not take the integration down with it.
        return 0.0
    return _clamp((db - vpl) / (vph - vpl), 0.0, 1.0)


# Binary floating point cannot represent most of the fractions a UI sends, so an input that is
# mathematically an exact half-dB can arrive a hair to one side of it: 0.55 * 50 is
# 27.499999999999996, not 27.5. Rounded directly, that tie goes UP - louder - which is the one
# direction the tie rule exists to forbid.
#
# Measured, rather than assumed: over -50..0, 50 of the 101 round percentages a UI sends are
# exact ties and exactly one of them (55%, -22.5 dB) lands on the wrong side without this snap.
# Over -80..10 and -90..0 it is also one; over -127..0 and -60..-5, none. So the count is small
# and range-dependent -- but it is never zero by design, the affected input is unpredictable,
# and the error is always in the louder direction.
#
# Snapping to nine decimal places first restores the tie the arithmetic was meant to produce.
# Nine is far tighter than any real dB value needs and far looser than the error involved.
_TIE_PRECISION = 9


def fraction_to_db(fraction: float, vpl: float, vph: float) -> int:
    """A Home Assistant `volume_level` to an integer dB the unit will accept.

    The bounds are rounded *inward* — `ceil(vpl)` and `floor(vph)` — so a fractional range like
    -127.5..0 still yields a whole number that sits inside what the unit reported, rather than
    one half-step outside it.
    """
    low, high = math.ceil(vpl), math.floor(vph)
    if vph <= vpl or high < low:
        return low
    raw = vpl + _clamp(fraction, 0.0, 1.0) * (vph - vpl)
    return int(_clamp(round_half_down(round(raw, _TIE_PRECISION)), low, high))


# --------------------------------------------------------------------------------------
# Codecs
# --------------------------------------------------------------------------------------


class Codec:
    """Translates one wire representation of a two-state value to and from `bool`.

    Both codecs deliberately *decode* either wire shape while only *matching* their declared
    one. The unit is inconsistent here — `/muted` and `/powerIsOn` are JSON booleans while
    `/loudness` and `/bassenhance` are the strings "on" and "off" — and `/eq/tc` has not been
    measured on real firmware yet (HW-02).

    Tolerating both shapes means a wrong declaration degrades to a log line rather than to a
    control that silently does nothing, while `matches` still lets the mirror report which
    shape actually arrived.
    """

    __slots__ = ()

    def decode(self, raw: Any) -> bool | None:
        """Wire value to `bool`, or None if it cannot be read.

        Unreadable is not False. A control whose value is unknown must report unknown rather
        than quietly claiming to be off.
        """
        if raw is True or raw is False:
            return raw
        if raw == "on":
            return True
        if raw == "off":
            return False
        return None

    def matches(self, raw: Any) -> bool:
        """True when `raw` is in this codec's declared wire shape."""
        raise NotImplementedError

    def encode(self, value: bool) -> Any:
        raise NotImplementedError


class BoolCodec(Codec):
    """For paths the unit reports as JSON booleans, such as `/muted` and `/powerIsOn`."""

    __slots__ = ()

    def matches(self, raw: Any) -> bool:
        return raw is True or raw is False

    def encode(self, value: bool) -> bool:
        return bool(value)


class OnOffStringCodec(Codec):
    """For paths the unit reports as "on"/"off", such as `/loudness` and `/bassenhance`."""

    __slots__ = ()

    def matches(self, raw: Any) -> bool:
        return raw in ("on", "off")

    def encode(self, value: bool) -> str:
        return "on" if value else "off"


BOOL_CODEC = BoolCodec()
ON_OFF_CODEC = OnOffStringCodec()


# --------------------------------------------------------------------------------------
# Value types
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InputInfo:
    """One entry of `/inputs`. `key` is what gets written to `/input`."""

    key: str
    label: str = ""
    visible: bool = False


@dataclass(frozen=True, slots=True)
class DiracSlot:
    """One row of `/cal/slots`.

    `index` is authoritative: `/cal/currentdiracslot` is a 0-based index into the array, so a
    slot with no name still has to occupy its row. Dropping unnamed slots would misalign every
    slot after it.
    """

    index: int
    name: str = ""


@dataclass(frozen=True, slots=True)
class Versions:
    """Identity from `/versions`, normalised for display."""

    serial: str | None = None
    system: str | None = None
    av_controller: str | None = None


def normalise_av_controller(raw: Any) -> str | None:
    """`"5.96 Built Jul  8 2026, 11:45:00\\n"` to `"5.96"`.

    This is an internal component version on its own numbering, not the release the unit calls
    itself. Showing the whole string under a label a human reads as "firmware" is misleading,
    and the build timestamp is noise.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.split()[0]


def normalise_sw_version(raw: Any) -> str | None:
    """The release the unit calls itself everywhere a human looks: `V2.1.1`, `V1.13.3`."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()
