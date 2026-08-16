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

# The unit has TWO ways of going quiet, and they are not interchangeable. Its own web UI
# presents them as separate buttons with separate warnings:
#
#   /powerAction: "sleep"  — "Turn off front panel and sleep awaiting fast wake up".
#                            The network stays up, so Home Assistant can still see it and can
#                            wake it again. This is what a media player's "turn off" means.
#   /powerAction: "off"    — "Orderly shutdown the system and enter low power state".
#                            **The network goes with it.** Measured 2026-08-16 on the lab unit:
#                            no answer on port 80 within ten seconds, still nothing after four
#                            minutes, and the unit had to be started from its front panel.
#
# Mapping "turn off" to shutdown would mean Home Assistant loses the device every time someone
# turned a room off, and could never turn it back on.
POWER_OFF_SLEEP: Final = "sleep"
POWER_OFF_SHUTDOWN: Final = "off"
POWER_OFF_NOTHING: Final = "do_nothing"
POWER_OFF_ACTIONS: Final = (POWER_OFF_SLEEP, POWER_OFF_SHUTDOWN, POWER_OFF_NOTHING)
DEFAULT_POWER_OFF_ACTION: Final = POWER_OFF_SLEEP

# Sleep keeps the network, so `TURN_ON` is a real capability rather than a button that cannot
# work. This is the vendor's documented behaviour and the owner's experience of these units; we
# have measured the *shutdown* half directly but not yet the sleep half. HW-01b tracks that.
SLEEP_KEEPS_NETWORK: Final = True

# Shutdown ends communication until someone walks to the unit. Measured, not inferred. This is
# why the shutdown control is a separate, deliberately opt-in button rather than anything a
# `turn_off` service call can reach.
SHUTDOWN_ENDS_COMMUNICATION: Final = True

# How long setup waits for the first document before giving up and letting Home Assistant
# retry. The client's own connect deadline is 15 s; this leaves room for it to fire first and
# report the more specific error.
SETUP_TIMEOUT: Final = 20.0
