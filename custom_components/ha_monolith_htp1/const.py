"""Constants for the HA Monolith HTP1 integration.

Every non-obvious number here carries a comment naming the measurement or the defect that
produced it. The HTP-1 protocol facts were verified live against firmware 1.13.3 and 2.1.1
during the Control4 Monolith HTP-1 driver project; see docs/ai/design/ for the record.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "ha_monolith_htp1"

MANUFACTURER: Final = "Monoprice"
MODEL: Final = "Monolith HTP-1"

# The only control path the unit exposes. There is no REST API -- /api, /mso and /status all
# return 404, and GET / serves the web UI. There is no TLS and no authentication.
WS_PATH: Final = "/ws/controller"
WS_PORT: Final = 80

# A unit can accept a TCP connection on port 80 *before* /ws/controller is live, typically
# while it is still booting. Without an explicit timeout covering both the connect and the
# handshake, a client waits forever with nothing able to move it out of that state. This was
# a Critical finding in the Control4 driver.
CONNECT_TIMEOUT: Final = 15.0

# aiohttp derives its pong deadline as heartbeat/2 and offers no second knob, so the Control4
# driver's 30 s ping / 10 s pong pair is not expressible here. 30 s gives a 15 s pong deadline
# and 45 s worst-case half-open detection, which sits inside the 60 s backoff cap.
WS_HEARTBEAT: Final = 30.0
