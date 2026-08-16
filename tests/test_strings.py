"""Translations, checked without importing Home Assistant.

Two failure modes, both silent in normal use.

`strings.json` and `translations/en.json` must stay byte-identical. They drift the moment
someone edits one, and the symptom is a config flow showing raw keys to a user rather than
prose — in a dialog most people see exactly once, while adding the integration.

And every message key the flow can actually emit must exist in the file. A flow that reports
`cannot_connect` when the file only defines `unknown` shows the user a bare identifier at the
exact moment they are already confused about why their processor will not connect.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = REPO_ROOT / "custom_components" / "ha_monolith_htp1"
STRINGS = INTEGRATION / "strings.json"
TRANSLATION = INTEGRATION / "translations" / "en.json"
CONFIG_FLOW = INTEGRATION / "config_flow.py"


def test_strings_and_translations_match():
    """AC-46. Byte-identical, not merely equivalent."""
    assert STRINGS.read_bytes() == TRANSLATION.read_bytes(), (
        "strings.json and translations/en.json have drifted; copy one over the other"
    )


def test_both_files_are_valid_json():
    for path in (STRINGS, TRANSLATION):
        json.loads(path.read_text(encoding="utf-8"))


def _flow_message_keys() -> tuple[set[str], set[str]]:
    """Error and abort keys the flow can emit, read out of the source.

    Errors are assignments like `errors["base"] = "cannot_connect"`; aborts are the `reason=`
    keyword. Reading the source rather than the doc means this cannot pass because someone
    updated a list by hand.
    """
    tree = ast.parse(CONFIG_FLOW.read_text(encoding="utf-8"))
    errors: set[str] = set()
    aborts: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "errors"
                    and isinstance(node.value.value, str)
                ):
                    errors.add(node.value.value)
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "reason" and isinstance(kw.value, ast.Constant):
                    aborts.add(kw.value.value)
    return errors, aborts


def test_the_message_scanner_finds_something():
    """A scanner that found nothing would make the checks below pass vacuously."""
    errors, aborts = _flow_message_keys()
    assert len(errors) >= 4, f"only found {errors}; has the flow's error style changed?"
    assert aborts, "expected at least one abort reason"


def test_every_flow_error_has_a_translation():
    """AC-47."""
    strings = json.loads(STRINGS.read_text(encoding="utf-8"))
    defined = set(strings["config"]["error"])
    emitted, _ = _flow_message_keys()
    assert emitted <= defined, f"config flow can emit untranslated errors: {emitted - defined}"


def test_every_flow_abort_has_a_translation():
    """AC-47. Home Assistant supplies some abort reasons itself, so only ours are checked."""
    strings = json.loads(STRINGS.read_text(encoding="utf-8"))
    defined = set(strings["config"]["abort"])
    _, emitted = _flow_message_keys()
    ours = {key for key in emitted if key in {"wrong_device"}}
    assert ours <= defined, f"config flow can abort with untranslated reasons: {ours - defined}"


def test_the_reserved_abort_reasons_are_translated():
    """Home Assistant raises these on our behalf; the text is still ours to write."""
    strings = json.loads(STRINGS.read_text(encoding="utf-8"))
    defined = set(strings["config"]["abort"])
    assert {"already_configured", "reconfigure_successful"} <= defined


@pytest.mark.parametrize("step", ["user", "reconfigure"])
def test_each_form_step_is_described(step):
    """Every step needs a title and a description; a bare form is a bad first impression."""
    strings = json.loads(STRINGS.read_text(encoding="utf-8"))
    section = strings["config"]["step"][step]
    assert section["title"]
    assert section["description"]
    assert section["data"]["host"]


def test_the_options_selector_has_translated_choices():
    """A dropdown showing `do_nothing` rather than "Do nothing" is a missing selector block."""
    strings = json.loads(STRINGS.read_text(encoding="utf-8"))
    options = strings["selector"]["power_off_action"]["options"]
    assert set(options) == {"off", "sleep", "do_nothing"}
    assert all(label and label != key for key, label in options.items())
