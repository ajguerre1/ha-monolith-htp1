"""Dropdown lists: display label to wire value, for sources, sound modes and Dirac slots.

Pure functions over the mirror's collections. Each returns an **ordered mapping of label to
wire value**, which is exactly what a Home Assistant select needs: `list(options)` is the
option list, and `options[chosen]` is what to write.

Three rules, each of which fixes a visible defect:

- **Canonical order, never dictionary order.** JSON object order is not a contract. A unit that
  reordered its `/inputs` map between documents would otherwise reshuffle every dropdown in the
  house on reconnect.
- **The current value is always present.** Home Assistant renders a blank selector when the
  reported value is missing from the option list, and an input can legitimately be selected
  while marked invisible.
- **Duplicate labels disambiguate every colliding member.** Suffixing only the later occurrence
  would reintroduce the order dependence the first rule removes.
"""

from __future__ import annotations

from .models import DiracSlot, InputInfo

# Fixed presentation order. Everything the unit supports, whether or not this document
# mentioned it.
CANONICAL_INPUT_ORDER: tuple[str, ...] = (
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "h7",
    "h8",
    "a1",
    "a2",
    "spdif1",
    "spdif2",
    "spdif3",
    "optical1",
    "optical2",
    "optical3",
    "aes",
    "b",
    "tv",
    "usb",
    "roon",
)

# Used when an input carries no label of its own. A blank row in a dropdown is unusable.
DEFAULT_INPUT_LABELS: dict[str, str] = {
    **{f"h{n}": f"HDMI {n}" for n in range(1, 9)},
    **{f"a{n}": f"Analog {n}" for n in range(1, 3)},
    **{f"spdif{n}": f"Coax {n}" for n in range(1, 4)},
    **{f"optical{n}": f"Optical {n}" for n in range(1, 4)},
    "aes": "AES/EBU",
    "b": "Bluetooth",
    "tv": "eARC / TV",
    "usb": "USB Audio",
    "roon": "Roon",
}

# Vendor names, in the order the unit's own interface presents them.
SOUND_MODE_LABELS: tuple[tuple[str, str], ...] = (
    ("off", "Direct"),
    ("native", "Native"),
    ("dolby", "Dolby Surround"),
    ("dts", "DTS Neural:X"),
    ("auro", "Auro-3D"),
    ("mono", "Mono"),
    ("stereo", "Stereo"),
)


def _default_input_label(key: str) -> str:
    return DEFAULT_INPUT_LABELS.get(key, key.upper())


def source_options(inputs: dict[str, InputInfo], current: str | None = None) -> dict[str, str]:
    """Ordered mapping of display label to input key."""
    keys = [key for key in CANONICAL_INPUT_ORDER if _offer_input(inputs, key, current)]
    # Keys the unit reported that we have never heard of still deserve a place, after the
    # known ones so the familiar list stays stable.
    keys += sorted(
        key
        for key in inputs
        if key not in CANONICAL_INPUT_ORDER and _offer_input(inputs, key, current)
    )

    labels = {
        key: (inputs[key].label if key in inputs else "") or _default_input_label(key)
        for key in keys
    }

    # Every member of a collision is suffixed, so the result cannot depend on iteration order.
    counts: dict[str, int] = {}
    for label in labels.values():
        counts[label] = counts.get(label, 0) + 1

    options: dict[str, str] = {}
    for key, label in labels.items():
        display = f"{label} ({key})" if counts[label] > 1 else label
        options[display] = key
    return options


def _offer_input(inputs: dict[str, InputInfo], key: str, current: str | None) -> bool:
    if key == current:
        # Always offered: `source` must appear in `source_list` or the frontend goes blank.
        return True
    info = inputs.get(key)
    return info is not None and info.visible


def sound_mode_options(
    upmix_visible: dict[str, bool], current: str | None = None
) -> dict[str, str]:
    """Ordered mapping of display label to upmix key.

    A mode with no visibility flag is shown. Firmware 1.13.x omits `homevis` entirely, and
    hiding every mode would be a worse failure than showing one the user does not want.
    """
    options: dict[str, str] = {}
    for key, label in SOUND_MODE_LABELS:
        if key == current or upmix_visible.get(key, True):
            options[label] = key
    return options


def dirac_slot_options(slots: list[DiracSlot]) -> dict[str, int]:
    """Ordered mapping of display label to slot index.

    Labelled by wire index, so the number the user sees is the number
    `/cal/currentdiracslot` uses. The prefix also makes duplicate names unique for free, and
    keeps ordering stable regardless of what the slots are called.
    """
    return {
        (f"{slot.index} - {slot.name}" if slot.name else f"{slot.index} - Slot {slot.index}"): (
            slot.index
        )
        for slot in slots
    }
