"""Value semantics: the volume map, the codecs, and the version strings.

This is the highest-consequence module in the milestone. Everything else either moves bytes or
mirrors state; this one decides what number reaches a processor in an occupied room, and it is
the one place where being wrong is audible rather than merely visible.

The volume map carries a defect that was caught in review rather than in production, and these
tests exist to keep it caught. The Control4 driver for this same device converts dB to an
*integer percentage*, because a Control4 room endpoint takes one. Home Assistant's
`volume_level` is a float. Porting the quantisation looks obviously right and is silently
lossy: over a -127..0 range, 27 of 128 dB values fail to round-trip, and the first failure
returns one dB LOUDER than requested — the exact direction the tie rule exists to prevent.

So: the fraction is never rounded, and half-down rounding applies only on the way back to
integer dB.
"""

from __future__ import annotations

import math
from fractions import Fraction

import pytest

from custom_components.ha_monolith_htp1.htp1 import models

# Ranges worth testing. (-50, 0) is what both real units report today, (-80, 10) exercises a
# positive ceiling, and (-127, 0) is the one that exposed the quantisation defect.
RANGES = [(-50, 0), (-80, 10), (-127, 0)]


# --------------------------------------------------------------------------------------
# Rounding
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.5, 0),
        (1.5, 1),
        (2.5, 2),
        (-0.5, -1),
        (-1.5, -2),
        (-49.5, -50),
        (0.4, 0),
        (0.6, 1),
        (-0.4, 0),
        (-0.6, -1),
        (3.0, 3),
        (-3.0, -3),
    ],
)
def test_round_half_down_sends_every_tie_downward(value, expected):
    assert models.round_half_down(value) == expected


def test_round_half_down_is_not_bankers_rounding():
    """Python's built-in `round` is banker's rounding, and it is wrong here in a subtle way.

    It rounds half to *even*, so 1.5 goes up to 2 while 2.5 goes down to 2. Half of all ties
    would therefore end up louder than requested. This test fails the moment someone
    "simplifies" `round_half_down` into `round`.
    """
    assert round(1.5) == 2 and models.round_half_down(1.5) == 1
    assert round(2.5) == 2 and models.round_half_down(2.5) == 2
    assert round(0.5) == 0 and models.round_half_down(0.5) == 0


# --------------------------------------------------------------------------------------
# The volume map
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("vpl", "vph"), RANGES)
def test_every_db_survives_a_round_trip(vpl, vph):
    """The highest-value test in the suite.

    `(-127, 0)` is the case that matters: 128 dB values cannot survive a 101-step integer
    percentage, so this fails outright if the fraction is ever quantised.
    """
    for db in range(vpl, vph + 1):
        fraction = models.db_to_fraction(db, vpl, vph)
        assert models.fraction_to_db(fraction, vpl, vph) == db, (
            f"{db} dB did not survive a round trip over ({vpl}, {vph})"
        )


def test_the_fraction_is_never_quantised():
    """The regression guard for the ported-quantisation defect.

    Over -127..0, -125 dB is 1.5748...% — a value no 101-step percentage can represent. If this
    starts landing on a whole percent, the Control4 behaviour has been reintroduced.
    """
    fraction = models.db_to_fraction(-125, -127, 0)
    percent = fraction * 100
    assert abs(percent - round(percent)) > 1e-9, (
        f"{percent!r} is a whole percent, so the fraction has been quantised"
    )


def test_the_fraction_is_a_float_between_zero_and_one():
    """Home Assistant's `volume_level` contract."""
    for vpl, vph in RANGES:
        for db in range(vpl, vph + 1):
            fraction = models.db_to_fraction(db, vpl, vph)
            assert isinstance(fraction, float)
            assert 0.0 <= fraction <= 1.0


def test_the_endpoints_map_to_zero_and_one():
    for vpl, vph in RANGES:
        assert models.db_to_fraction(vpl, vpl, vph) == 0.0
        assert models.db_to_fraction(vph, vpl, vph) == 1.0


def test_ties_round_down_never_up():
    """Over -50..0 roughly half the round percentages a UI sends land exactly on a half-dB.

    The tie rule is therefore not an edge case; it decides most of the inputs this will ever
    see. On a tie, the volume must end up quieter than asked.

    Ties are identified with exact rational arithmetic rather than floats. `0.55 * 50` is
    `27.499999999999996` in binary floating point, so asking a float whether it is a tie gets
    the wrong answer for exactly the inputs this test is about — which is the defect that made
    `fraction_to_db` snap before rounding in the first place.
    """
    vpl, vph = -50, 0
    ties = 0
    for percent in range(101):
        exact = Fraction(vpl) + Fraction(percent, 100) * Fraction(vph - vpl)
        if exact.denominator != 2:  # not an exact half-dB
            continue
        ties += 1
        assert models.fraction_to_db(percent / 100, vpl, vph) == math.floor(exact), (
            f"{percent}% is exactly {float(exact)} dB and must round down"
        )
    assert ties > 40, f"expected the tie rule to decide most inputs, but only {ties} were ties"


def test_a_tie_arriving_with_floating_point_error_still_rounds_down():
    """The specific regression: 55% of -50..0 is -22.5 dB, and must land on -23, not -22.

    Computed naively the intermediate is -22.499999999999996, which rounds to -22 — one dB
    louder than requested. Measured across five plausible ranges, one input per range is
    affected on three of them and none on the other two, so this is rare rather than
    widespread. It is worth guarding anyway: which input is hit depends on the range, `vpl` and
    `vph` are user-configurable, and the error is always in the louder direction.
    """
    assert -50 + 0.55 * 50 != -22.5, "if this holds, the platform changed and the guard is moot"
    assert models.fraction_to_db(0.55, -50, 0) == -23


@pytest.mark.parametrize(("vpl", "vph"), RANGES)
def test_values_outside_the_range_are_clamped(vpl, vph):
    assert models.db_to_fraction(vpl - 100, vpl, vph) == 0.0
    assert models.db_to_fraction(vph + 100, vpl, vph) == 1.0
    assert models.fraction_to_db(-1.0, vpl, vph) == vpl
    assert models.fraction_to_db(2.0, vpl, vph) == vph


@pytest.mark.parametrize(("vpl", "vph"), [(0, 0), (0, -50), (-10, -10), (5, -5)])
def test_a_degenerate_volume_range_does_not_divide_by_zero(vpl, vph):
    """A unit reporting a nonsense range must not take the integration down with it."""
    assert models.db_to_fraction(-20, vpl, vph) == 0.0
    assert models.fraction_to_db(0.5, vpl, vph) == vpl


def test_fractional_range_bounds_stay_inside_the_device_range():
    """`vpl`/`vph` are user-configurable and need not be whole numbers.

    The result must still be an integer dB the unit will accept, and must never fall outside
    the range it reported.
    """
    vpl, vph = -127.5, 0.0
    for fraction in (0.0, 0.001, 0.5, 0.999, 1.0):
        db = models.fraction_to_db(fraction, vpl, vph)
        assert isinstance(db, int)
        assert vpl <= db <= vph


# --------------------------------------------------------------------------------------
# Codecs
# --------------------------------------------------------------------------------------


def test_the_boolean_codec_round_trips():
    codec = models.BOOL_CODEC
    assert codec.decode(True) is True
    assert codec.decode(False) is False
    assert codec.encode(True) is True
    assert codec.encode(False) is False


def test_the_on_off_string_codec_round_trips():
    codec = models.ON_OFF_CODEC
    assert codec.decode("on") is True
    assert codec.decode("off") is False
    assert codec.encode(True) == "on"
    assert codec.encode(False) == "off"


def test_each_codec_tolerates_the_other_wire_shape():
    """`/eq/tc` is declared boolean but unverified on real firmware (HW-02).

    Tolerating both shapes means a wrong declaration degrades to a log line rather than to a
    switch that silently does nothing.
    """
    assert models.BOOL_CODEC.decode("on") is True
    assert models.BOOL_CODEC.decode("off") is False
    assert models.ON_OFF_CODEC.decode(True) is True
    assert models.ON_OFF_CODEC.decode(False) is False


@pytest.mark.parametrize("raw", [None, "yes", "", 1, 0, [], {}, "ON "])
def test_a_codec_returns_none_for_a_value_it_cannot_read(raw):
    """Unreadable is not the same as False. A switch must go unknown, not silently off."""
    assert models.BOOL_CODEC.decode(raw) is None
    assert models.ON_OFF_CODEC.decode(raw) is None


def test_a_codec_can_tell_whether_the_wire_shape_matched_its_declaration():
    """This is what lets the mirror report a firmware mismatch instead of guessing forever."""
    assert models.BOOL_CODEC.matches(True)
    assert not models.BOOL_CODEC.matches("on")
    assert models.ON_OFF_CODEC.matches("on")
    assert not models.ON_OFF_CODEC.matches(True)


# --------------------------------------------------------------------------------------
# Version strings
# --------------------------------------------------------------------------------------


def test_the_av_controller_version_is_reduced_to_its_number():
    """The raw value is `5.96 Built Jul  8 2026, 11:45:00\\n`.

    Showing that under a label a human reads as "firmware" is actively misleading, and the
    build date is not what anyone is looking for.
    """
    raw = "5.96 Built Jul  8 2026, 11:45:00\n"
    assert models.normalise_av_controller(raw) == "5.96"


def test_the_system_version_is_the_one_the_unit_calls_itself():
    assert models.normalise_sw_version("V2.1.1") == "V2.1.1"
    assert models.normalise_sw_version("  V1.13.3 \n") == "V1.13.3"


@pytest.mark.parametrize("raw", [None, "", "   ", 42])
def test_version_normalisers_tolerate_absence(raw):
    assert models.normalise_av_controller(raw) is None
    assert models.normalise_sw_version(raw) is None
