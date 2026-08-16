"""The MSO mirror: the ~38 KB device document projected down to what this integration uses.

This is the only module a firmware revision forces anyone to edit, which is why it is separate
from `models.py` — a firmware diff should never scroll past the volume arithmetic.

The mirror is a **projection, not a copy**. About thirty scalar leaves plus three collections
are tracked; everything else is classified and dropped without being walked. `/status/raw` in
particular is a large nested blob of decoder internals, and mirroring it would defeat the point.

Four rules, each of which is silent when broken:

1. **Container replaces re-derive their leaves.** The unit sends `replace` on whole subtrees.
2. **Absent is unspecified, not cleared** — except in a full document, which is a census.
3. **`/cal/slots` always has six rows.** `/cal/currentdiracslot` indexes it positionally.
4. **The change set contains only fields that actually moved.** Roughly fifty wall panels
   receive every state change downstream, so a spurious change is a performance defect.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import (
    BOOL_CODEC,
    ON_OFF_CODEC,
    Codec,
    DiracSlot,
    InputInfo,
    Versions,
    normalise_av_controller,
    normalise_sw_version,
)

# The Dirac slot array is a fixed six rows on every firmware seen. `/cal/currentdiracslot` is a
# 0-based index into it, so an unnamed slot still has to occupy its position.
DIRAC_SLOT_COUNT = 6

# Change-set tokens for the three collections, which do not have a single scalar path.
FIELD_INPUTS = "inputs"
FIELD_DIRAC_SLOTS = "dirac_slots"
FIELD_UPMIX_VISIBLE = "upmix_visible"


@dataclass(frozen=True, slots=True)
class Field:
    """One tracked leaf: where it lives on the wire and how to read it."""

    name: str
    codec: Codec | None = None
    normaliser: Callable[[Any], Any] | None = None

    def read(self, raw: Any) -> Any:
        if self.codec is not None:
            return self.codec.decode(raw)
        if self.normaliser is not None:
            return self.normaliser(raw)
        return raw


TRACKED_PATHS: dict[str, Field] = {
    "/volume": Field("volume"),
    "/muted": Field("muted", codec=BOOL_CODEC),
    "/powerIsOn": Field("power", codec=BOOL_CODEC),
    "/powerAction": Field("power_action"),
    "/input": Field("input"),
    "/upmix/select": Field("upmix"),
    # Strings on the wire, not JSON booleans. The asymmetry is the unit's, not ours.
    "/loudness": Field("loudness", codec=ON_OFF_CODEC),
    "/bassenhance": Field("bass_enhance", codec=ON_OFF_CODEC),
    # Declared boolean but never measured on real firmware (HW-02). The codec decodes either
    # shape and the mirror reports a mismatch once, so a wrong declaration is visible rather
    # than silently inert.
    "/eq/tc": Field("tone_control", codec=BOOL_CODEC),
    "/night": Field("night"),
    "/dialogEnh": Field("dialog_enhance"),
    "/cal/vpl": Field("vpl"),
    "/cal/vph": Field("vph"),
    "/cal/currentdiracslot": Field("dirac_slot"),
    "/cal/diracactive": Field("dirac_active"),
    "/cal/lipsync": Field("lip_sync"),
    "/unitname": Field("unit_name"),
    "/versions/SerialNumber": Field("serial"),
    "/versions/swVer": Field("system_version", normaliser=normalise_sw_version),
    "/versions/avController": Field("av_controller", normaliser=normalise_av_controller),
    "/status/SurroundMode": Field("surround_mode"),
    "/status/DECSourceProgram": Field("source_program"),
    "/status/DECProgramFormat": Field("program_format"),
    "/status/DECSampleRate": Field("input_sample_rate"),
    "/status/ENCListeningFormat": Field("listening_format"),
    "/status/ENCSampleRate": Field("output_sample_rate"),
    "/status/DiracState": Field("dirac_status"),
    "/videostat/VideoResolution": Field("video_resolution"),
    "/videostat/VideoColorSpace": Field("video_color_space"),
    "/videostat/HDRstatus": Field("hdr_status"),
}

# Subtrees the unit replaces wholesale, sending the entire sub-object as the value.
CONTAINER_PREFIXES = frozenset(
    {
        "/cal",
        "/cal/slots",
        "/inputs",
        "/status",
        "/svronly",
        "/upmix",
        "/versions",
        "/videostat",
    }
)

# Paths this integration may write. Deliberately an allowlist rather than "everything tracked":
# `/status/*`, `/videostat/*` and `/versions/*` are what the unit reports about itself, and
# writing one would at best be ignored. The unit rejects an entire `changemso` if a single
# operation targets a member it does not have, so one bad path silently voids every other write
# coalesced into the same flush.
WRITABLE_PATHS = frozenset(
    {
        "/volume",
        "/muted",
        "/powerIsOn",
        "/powerAction",
        "/input",
        "/upmix/select",
        "/loudness",
        "/bassenhance",
        "/eq/tc",
        "/night",
        "/dialogEnh",
        "/cal/currentdiracslot",
        "/cal/diracactive",
        "/cal/lipsync",
    }
)

# Per-input delay is writable too, and is not a tracked scalar: the vendor's own client writes
# `/cal/lipsync` and `/inputs/<current input>/delay` together.
WRITABLE_INPUT_DELAY = re.compile(r"^/inputs/[^/]+/delay$")

_INPUT_LEAF = re.compile(r"^/inputs/([^/]+)/(label|visible)$")
_UPMIX_HOMEVIS = re.compile(r"^/upmix/([^/]+)/homevis$")
_SLOT_LEAF = re.compile(r"^/cal/slots/(\d+)(?:/name)?$")


def _slot_name(row: Any) -> str:
    """The name of one `/cal/slots` row, for either unnamed shape.

    Both `{"name": ""}` and a row with no `name` key at all appear in the wild, and a missing
    row is possible too. All three are the same thing to a consumer: a slot that exists and has
    no name.
    """
    if isinstance(row, dict):
        name = row.get("name")
        return name if isinstance(name, str) else ""
    return ""


def _resolve(container: Any, pointer: str) -> tuple[Any, bool]:
    """Walk a relative JSON pointer. Returns (value, found)."""
    current = container
    for token in pointer.split("/"):
        if not isinstance(current, dict) or token not in current:
            return None, False
        current = current[token]
    return current, True


class MsoMirror:
    """Device truth, projected. Only `apply_document` and `apply_ops` write to it."""

    def __init__(self) -> None:
        self._fields: dict[str, Any] = {}
        self._present: set[str] = set()
        self._inputs: dict[str, InputInfo] = {}
        self._slots: list[DiracSlot] = [DiracSlot(index=i) for i in range(DIRAC_SLOT_COUNT)]
        self._upmix_visible: dict[str, bool] = {}
        self._mismatches: list[str] = []
        self._loaded = False

    # -- reads ---------------------------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._loaded

    def get(self, name: str) -> Any:
        return self._fields.get(name)

    def has(self, name: str) -> bool:
        """Whether this firmware reported the field at all.

        Distinct from a `None` value: absent means the feature does not exist here and should
        be disabled, rather than existing with an unknown value.
        """
        return name in self._present

    @property
    def inputs(self) -> dict[str, InputInfo]:
        return dict(self._inputs)

    @property
    def dirac_slots(self) -> list[DiracSlot]:
        return list(self._slots)

    @property
    def upmix_visible(self) -> dict[str, bool]:
        return dict(self._upmix_visible)

    @property
    def versions(self) -> Versions:
        return Versions(
            serial=self.get("serial"),
            system=self.get("system_version"),
            av_controller=self.get("av_controller"),
        )

    @property
    def mismatches(self) -> tuple[str, ...]:
        """Paths whose wire shape contradicted the declared codec, reported once each."""
        return tuple(self._mismatches)

    # -- writes --------------------------------------------------------------------------

    def apply_document(self, document: Any) -> frozenset[str]:
        """Apply a full `mso` document.

        This is the one place members may legitimately disappear: the document is a census of
        what the unit currently has, so a field it omits is gone rather than unspecified.
        """
        if not isinstance(document, dict):
            return frozenset()

        changed: set[str] = set()
        self._present.clear()

        for path, field in TRACKED_PATHS.items():
            raw, found = _resolve(document, path.lstrip("/"))
            if found:
                self._present.add(field.name)
                self._note_mismatch(path, field, raw)
                value = field.read(raw)
            else:
                value = None
            if self._assign(field.name, value):
                changed.add(field.name)

        if self._rebuild_inputs(document.get("inputs"), census=True):
            changed.add(FIELD_INPUTS)
        cal = document.get("cal")
        slots = cal.get("slots") if isinstance(cal, dict) else None
        if self._rebuild_slots(slots):
            changed.add(FIELD_DIRAC_SLOTS)
        if self._rebuild_upmix_visible(document.get("upmix"), census=True):
            changed.add(FIELD_UPMIX_VISIBLE)

        self._loaded = True
        return frozenset(changed)

    def apply_ops(self, ops: Any) -> frozenset[str]:
        """Apply patch operations. Never raises; unrecognised paths cost a dict lookup."""
        if not ops:
            return frozenset()

        changed: set[str] = set()
        for op in ops:
            if not isinstance(op, dict):
                continue
            path = op.get("path")
            if not isinstance(path, str):
                continue
            removing = op.get("op") == "remove"
            value = None if removing else op.get("value")
            changed |= self._apply_one(path, value, removing)
        return frozenset(changed)

    # -- internals -----------------------------------------------------------------------

    def _apply_one(self, path: str, value: Any, removing: bool) -> set[str]:
        field = TRACKED_PATHS.get(path)
        if field is not None:
            if removing:
                self._present.discard(field.name)
                return {field.name} if self._assign(field.name, None) else set()
            self._present.add(field.name)
            self._note_mismatch(path, field, value)
            return {field.name} if self._assign(field.name, field.read(value)) else set()

        if path in CONTAINER_PREFIXES:
            return self._apply_container(path, value)

        match = _INPUT_LEAF.match(path)
        if match:
            key, leaf = match.group(1), match.group(2)
            return {FIELD_INPUTS} if self._merge_input(key, {leaf: value}) else set()

        match = _UPMIX_HOMEVIS.match(path)
        if match:
            moved = self._set_upmix_visible(match.group(1), value)
            return {FIELD_UPMIX_VISIBLE} if moved else set()

        match = _SLOT_LEAF.match(path)
        if match:
            index = int(match.group(1))
            name = value.get("name") if isinstance(value, dict) else value
            return {FIELD_DIRAC_SLOTS} if self._set_slot(index, name) else set()

        # Not a path this integration reads. A dict lookup and three anchored matches is the
        # entire cost, which is what keeps the /status/raw blob free.
        return set()

    def _apply_container(self, prefix: str, value: Any) -> set[str]:
        """Re-derive every tracked leaf beneath a wholesale subtree replace.

        Leaves the value does not mention are left alone rather than cleared: a partial
        `/inputs` replace naming three inputs must not wipe the other eighteen.
        """
        changed: set[str] = set()

        if prefix == "/cal/slots":
            if self._rebuild_slots(value):
                changed.add(FIELD_DIRAC_SLOTS)
            return changed

        if not isinstance(value, dict):
            return changed

        for path, field in TRACKED_PATHS.items():
            if not path.startswith(prefix + "/"):
                continue
            raw, found = _resolve(value, path[len(prefix) + 1 :])
            if not found:
                continue
            self._present.add(field.name)
            self._note_mismatch(path, field, raw)
            if self._assign(field.name, field.read(raw)):
                changed.add(field.name)

        if prefix == "/inputs":
            for key, info in value.items():
                if isinstance(info, dict) and self._merge_input(key, info):
                    changed.add(FIELD_INPUTS)
        elif prefix == "/cal" and "slots" in value and self._rebuild_slots(value["slots"]):
            changed.add(FIELD_DIRAC_SLOTS)
        elif prefix == "/upmix" and self._rebuild_upmix_visible(value, census=False):
            changed.add(FIELD_UPMIX_VISIBLE)

        return changed

    def _assign(self, name: str, value: Any) -> bool:
        """Store only if it actually moved. The first of three change-gating layers.

        A field that has never been seen reads as `None`, so setting it to `None` is not a
        change: it was unknown before and it is unknown now, and reporting that as movement
        would wake every entity on the first document for every field this firmware lacks.
        """
        if self._fields.get(name) == value:
            return False
        self._fields[name] = value
        return True

    def _note_mismatch(self, path: str, field: Field, raw: Any) -> None:
        """Record a wire shape that contradicts the declared codec, once per path.

        Once, because a connection that pushes the same path every second would otherwise
        produce an unbounded stream of identical warnings.
        """
        if field.codec is None or raw is None:
            return
        if not field.codec.matches(raw) and path not in self._mismatches:
            self._mismatches.append(path)

    def _rebuild_inputs(self, value: Any, *, census: bool) -> bool:
        if not isinstance(value, dict):
            return False
        before = dict(self._inputs)
        if census:
            self._inputs = {}
        for key, info in value.items():
            if isinstance(info, dict):
                self._merge_input(key, info)
        return self._inputs != before

    def _merge_input(self, key: str, patch: dict) -> bool:
        existing = self._inputs.get(key, InputInfo(key=key))
        updated = InputInfo(
            key=key,
            label=patch.get("label", existing.label) or "",
            visible=bool(patch.get("visible", existing.visible)),
        )
        if updated == existing:
            return False
        self._inputs[key] = updated
        return True

    def _rebuild_slots(self, value: Any) -> bool:
        """Always six rows, positionally indexed, whatever the unit sent.

        Both unnamed shapes appear in the wild — `{"name": ""}` and `{}` — and dropping either
        would misalign the array against `/cal/currentdiracslot`.
        """
        before = list(self._slots)
        rows = value if isinstance(value, list) else []
        self._slots = [
            DiracSlot(index=i, name=_slot_name(rows[i] if i < len(rows) else None))
            for i in range(DIRAC_SLOT_COUNT)
        ]
        return self._slots != before

    def _set_slot(self, index: int, name: Any) -> bool:
        if not 0 <= index < DIRAC_SLOT_COUNT:
            return False
        updated = DiracSlot(index=index, name=name if isinstance(name, str) else "")
        if self._slots[index] == updated:
            return False
        self._slots[index] = updated
        return True

    def _rebuild_upmix_visible(self, value: Any, *, census: bool) -> bool:
        if not isinstance(value, dict):
            return False
        before = dict(self._upmix_visible)
        if census:
            self._upmix_visible = {}
        for mode, config in value.items():
            if isinstance(config, dict) and "homevis" in config:
                self._upmix_visible[mode] = bool(config["homevis"])
        return self._upmix_visible != before

    def _set_upmix_visible(self, mode: str, value: Any) -> bool:
        visible = bool(value)
        if self._upmix_visible.get(mode) == visible:
            return False
        self._upmix_visible[mode] = visible
        return True
