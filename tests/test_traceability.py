"""Every acceptance criterion must name a test that actually exists.

The requirements doc promises a table mapping each AC to the test that proves it. That promise
is only worth something if it stays true, and it does not stay true on its own: test names get
sharper as behaviour gets clearer, tests get split, and the doc quietly stops matching.

This was not hypothetical. A traceability audit at the end of M1 found **nine of twenty-one**
criteria naming tests that no longer existed under those names. Every one turned out to be a
rename or a split rather than missing coverage — but that is exactly the point. A reader
auditing the table would have had to establish that nine times over, and the tenth might have
been a real gap.

So the table is now enforced rather than maintained by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO_ROOT / "docs" / "ai" / "requirements" / "2026-08-15-feature-htp1-client.md"
TESTS_DIR = Path(__file__).parent

# | AC-01 | criterion text | `test_one`, `test_two` |
_AC_ROW = re.compile(r"^\|\s*(AC-\d+)\s*\|(.+?)\|(.+?)\|\s*$", re.M)
_TEST_NAME = re.compile(r"`(test_[a-z0-9_]+)`")
_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(test_[a-z0-9_]+)", re.M)


def _criteria() -> list[tuple[str, list[str]]]:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    return [(ac, _TEST_NAME.findall(tests)) for ac, _criterion, tests in _AC_ROW.findall(text)]


def _defined_tests() -> set[str]:
    """Every test defined under tests/, by parsing rather than by importing.

    Importing would drag in the Home Assistant-dependent modules this suite deliberately avoids.
    """
    names: set[str] = set()
    for path in TESTS_DIR.rglob("test_*.py"):
        names.update(_DEF.findall(path.read_text(encoding="utf-8")))
    return names


def test_the_requirements_doc_still_has_an_acceptance_table():
    criteria = _criteria()
    assert len(criteria) >= 20, f"only found {len(criteria)} criteria; has the table moved?"


def test_every_acceptance_criterion_names_at_least_one_test():
    unnamed = [ac for ac, tests in _criteria() if not tests]
    assert not unnamed, f"these criteria name no test at all: {unnamed}"


def test_every_named_test_exists():
    """The guard that would have caught nine stale names at the end of M1."""
    defined = _defined_tests()
    missing = {
        ac: [name for name in tests if name not in defined]
        for ac, tests in _criteria()
        if any(name not in defined for name in tests)
    }
    assert not missing, (
        "the requirements doc names tests that do not exist — rename the doc, not the test, "
        f"if the behaviour is still covered: {missing}"
    )


def test_the_name_scanner_actually_finds_tests():
    """A scanner that found nothing would make the guard above pass vacuously."""
    defined = _defined_tests()
    assert len(defined) > 150, f"only found {len(defined)} tests; the scanner is probably broken"
    assert "test_every_named_test_exists" in defined
