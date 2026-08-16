"""The probe must be read-only by construction, and must not print the owner's house.

Both properties are enforced here rather than trusted, because this is the one tool in the
repository that gets pointed at five live processors in an occupied home, and it is short enough
that nobody will unit-test it line by line while editing it in a hurry.

Read-only is checked by parsing the script: it must never name `allow_writes` at all, and never
call a write method. That is stronger than checking it passes `False` — a script that cannot say
the word cannot enable writes by editing one character.

The scrubbing check matters because the probe's whole purpose is to be run against real units
and have its output pasted somewhere. A real `mso` carries the unit name, the owner's input
labels, their Dirac slot names and the serial number.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "scripts" / "probe_htp1.py"

WRITE_METHODS = {"async_write", "async_write_many"}


def _tree() -> ast.Module:
    return ast.parse(PROBE.read_text(encoding="utf-8"))


def test_the_probe_exists():
    assert PROBE.is_file(), "the probe is how the hardware questions get answered"


def test_the_probe_never_mentions_allow_writes():
    """AC-21. Stronger than passing False: a script that cannot say the word cannot enable it."""
    offenders = [
        node.arg
        for node in ast.walk(_tree())
        if isinstance(node, ast.keyword) and node.arg == "allow_writes"
    ]
    assert not offenders, "the probe must never pass allow_writes, not even allow_writes=False"


def test_the_probe_never_calls_a_write_method():
    called = {
        node.func.attr
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not (called & WRITE_METHODS), f"the probe calls {sorted(called & WRITE_METHODS)}"


def test_the_read_only_detector_actually_detects():
    """Prove the two guards above can fail before trusting them."""
    sample = ast.parse("client = Htp1Client(s, h, allow_writes=True)\nawait c.async_write('/a', 1)")
    keywords = [n.arg for n in ast.walk(sample) if isinstance(n, ast.keyword)]
    calls = {
        n.func.attr
        for n in ast.walk(sample)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "allow_writes" in keywords
    assert calls & WRITE_METHODS


# --------------------------------------------------------------------------------------
# Scrubbing
# --------------------------------------------------------------------------------------


@pytest.fixture
def summary(mso_modern):
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from probe_htp1 import summarise

    return summarise(mso_modern)


def test_the_summary_scrubs_site_data(summary, mso_modern):
    """Unit name, serial, input labels and Dirac slot names are the owner's, not ours."""
    blob = json.dumps(summary)
    secrets = [
        mso_modern["unitname"],
        mso_modern["versions"]["SerialNumber"],
        *(i["label"] for i in mso_modern["inputs"].values() if i["label"]),
        *(s.get("name") for s in mso_modern["cal"]["slots"] if s.get("name")),
    ]
    leaked = [s for s in secrets if s and s in blob]
    assert not leaked, f"the summary leaked site data: {leaked}"


def test_the_summary_answers_the_open_hardware_questions(summary):
    """HW-02, HW-03, HW-04 and HW-07 are the reason this tool exists."""
    assert summary["volume_range"] == {"vpl": -50, "vph": 0}  # HW-04
    assert summary["eq_tc"]["json_type"] == "bool"  # HW-02
    assert summary["mac_addresses_found"] == []  # HW-03
    assert summary["status_vocabulary"]["SurroundMode"]  # HW-07
    assert summary["firmware"]["swVer"] == "V2.1.1"


def test_the_summary_counts_rather_than_naming(summary):
    """Counts describe the unit; names describe the house."""
    assert summary["inputs"]["total"] == 21
    assert summary["inputs"]["visible"] == 7
    assert summary["dirac_slots"]["total"] == 6
    assert summary["dirac_slots"]["named"] == 5


def test_a_legacy_document_reports_the_missing_video_block(mso_legacy):
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from probe_htp1 import summarise

    result = summarise(mso_legacy)
    assert result["videostat_present"] is False
    assert result["volume_range"] == {"vpl": -60, "vph": -5}


def test_a_mac_address_is_reported_by_path_not_by_value():
    """HW-03 asks whether a MAC exists at all; the address itself is still site data."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from probe_htp1 import summarise

    result = summarise({"network": {"mac": "de:ad:be:ef:00:01"}, "cal": {}, "versions": {}})
    assert result["mac_addresses_found"] == ["/network/mac"]
    assert "de:ad:be:ef:00:01" not in json.dumps(result)
