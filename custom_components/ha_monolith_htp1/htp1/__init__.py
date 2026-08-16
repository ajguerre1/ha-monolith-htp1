"""Vendored client for the Monoprice Monolith HTP-1.

Kept inside the integration rather than published as a dependency so that `manifest.json` can
declare `requirements: []`. A `git+https` requirement would be refetched on every Home
Assistant restart, because `is_installed()` returns False for URL requirements.

Nothing in this package imports Home Assistant. That is what lets the whole client be tested on
a machine where Home Assistant cannot even be imported, and it is enforced by a test rather
than by good intentions.
"""

from __future__ import annotations

from .models import (
    BOOL_CODEC,
    ON_OFF_CODEC,
    DiracSlot,
    InputInfo,
    Versions,
    db_to_fraction,
    fraction_to_db,
    round_half_down,
)
from .mso import CONTAINER_PREFIXES, TRACKED_PATHS, MsoMirror
from .options import dirac_slot_options, sound_mode_options, source_options
from .protocol import (
    MessageKind,
    ParsedMessage,
    encode_change,
    encode_get_mso,
    normalise_ops,
    parse_message,
    replace_op,
)

__all__ = [
    "BOOL_CODEC",
    "CONTAINER_PREFIXES",
    "ON_OFF_CODEC",
    "TRACKED_PATHS",
    "DiracSlot",
    "InputInfo",
    "MessageKind",
    "MsoMirror",
    "ParsedMessage",
    "Versions",
    "db_to_fraction",
    "dirac_slot_options",
    "encode_change",
    "encode_get_mso",
    "fraction_to_db",
    "normalise_ops",
    "parse_message",
    "replace_op",
    "round_half_down",
    "sound_mode_options",
    "source_options",
]
