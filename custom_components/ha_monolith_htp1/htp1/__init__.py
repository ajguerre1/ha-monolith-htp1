"""Vendored client for the Monoprice Monolith HTP-1.

Kept inside the integration rather than published as a dependency so that `manifest.json` can
declare `requirements: []`. A `git+https` requirement would be refetched on every Home
Assistant restart, because `is_installed()` returns False for URL requirements.

Nothing in this package imports Home Assistant. That is what lets the whole client be tested on
a machine where Home Assistant cannot even be imported, and it is enforced by a test rather
than by good intentions.
"""

from __future__ import annotations

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
    "MessageKind",
    "ParsedMessage",
    "encode_change",
    "encode_get_mso",
    "normalise_ops",
    "parse_message",
    "replace_op",
]
