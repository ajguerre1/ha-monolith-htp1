"""Constants for the HA Monolith HTP1 integration.

Every non-obvious value carries a comment naming the measurement or the defect that produced it.
Protocol facts were verified live on firmware 1.13.3 and 2.1.1 during the Control4 Monolith
HTP-1 project, and re-measured on 2.1.2 across five units on 2026-08-16; see
`docs/ai/planning/backlog.md` for the evidence.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "ha_monolith_htp1"

MANUFACTURER: Final = "Monoprice"
MODEL: Final = "Monolith HTP-1"

# Options. Both change behaviour; neither duplicates something the entity registry already does.
CONF_POWER_OFF_ACTION: Final = "power_off_action"
CONF_MAX_VOLUME_DB: Final = "max_volume_db"

# What "turn off" should do. `do_nothing` exists because a room turning off, or a stray
# automation, should not be able to take a whole processor down.
POWER_OFF_STANDBY: Final = "off"
POWER_OFF_SLEEP: Final = "sleep"
POWER_OFF_NOTHING: Final = "do_nothing"
POWER_OFF_ACTIONS: Final = (POWER_OFF_STANDBY, POWER_OFF_SLEEP, POWER_OFF_NOTHING)
DEFAULT_POWER_OFF_ACTION: Final = POWER_OFF_STANDBY

# HW-01, still open: we do not know whether the unit keeps its network stack alive while
# `powerIsOn` is false. Both firmware families report `fastStart: "on"`, which strongly suggests
# yes, so we ship assuming yes and declare TURN_ON. Being wrong in that direction means the
# write simply never lands, because we are disconnected — which is the safe way to be wrong.
#
# Settling it needs a write to the designated lab unit and is deferred to M4. This constant is
# referenced in exactly one place, so flipping it is a one-line change.
POWER_OFF_KEEPS_NETWORK: Final = True

# How long setup waits for the first document before giving up and letting Home Assistant
# retry. The client's own connect deadline is 15 s; this leaves room for it to fire first and
# report the more specific error.
SETUP_TIMEOUT: Final = 20.0
