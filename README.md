# HA Monolith HTP1

A Home Assistant integration for the **Monoprice Monolith HTP-1** 16-channel AV processor,
installable and updatable through [HACS](https://hacs.xyz).

Push-based, no polling, no cloud, no runtime dependencies.

## Why this exists

The HTP-1 pushes every state change — including changes made on its front panel or in the
vendor's own web UI — to every connected client. That makes polling not just wasteful but
wrong: an idle connection was measured sending *zero* bytes over 90 seconds.

Design principles:

- **Push, never poll.** `update_interval` is `None`. State arrives when the unit says so.
- **The device's own values are the truth.** Volume is integer dB clamped to the unit's
  user-configurable range, and the Home Assistant 0–1 level is derived from the dB the unit
  *confirms* — never from what was requested.
- **Quiet on the bus and quiet in the log.** State is written only when something actually
  changed, checked at three separate layers. A unit switched off overnight produces a handful
  of log lines, not hundreds.
- **Absence tolerance everywhere.** A path the firmware does not report disables the feature
  that needs it instead of erroring.
- **No runtime dependencies.** The protocol client is vendored, so `manifest.json` keeps
  `requirements: []`.

## Entities

One device per processor, up to fourteen entities.

| Entity | Notes |
|---|---|
| `media_player` | Power, volume, mute, source, sound mode. Device class `receiver`. |
| `select` — Dirac slot | Addressed **by index**, labelled `0 - Reference`. Slots are often unnamed. |
| `select` — Dirac, Night mode | |
| `switch` — Loudness, Bass enhancement, Tone control | |
| `number` — Dialogue enhancement, Lip sync | |
| `sensor` ×3 — Surround mode, Source format, Listening format | Free text. Diagnostic. |
| `sensor` ×4 — Program format, sample rates, Dirac status | Disabled by default: they move on every content change. |
| `sensor` ×3 — Video resolution, HDR, Colour space | Not created on firmware without a video status block. |
| `button` — Shut down | **Disabled by default.** See below. |

Status sensors report `unknown` while the processor is off, rather than continuing to describe
the last thing it decoded.

## Power: sleep and shutdown are not the same thing

The HTP-1 has two ways of going quiet, and only one is recoverable.

| | Front panel | Network | Can Home Assistant turn it back on? |
|---|---|---|---|
| **Sleep** | off | **stays up** | yes |
| **Shut down** | off | goes with it | **no** |

`media_player.turn_off` **sleeps**. Shutting down would mean Home Assistant lost the device
every time someone turned a room off, with no way back — measured, the unit stopped answering
within ten seconds and had to be started from its own front panel.

Shutdown is therefore a **separate button, disabled by default**. Enabling it per processor in
the entity settings is the confirmation step. Only enable it if you are willing to walk to the
unit to undo it.

You can change what "turn off" means per entry in the integration's options, including
**Do nothing** — worth choosing if a stray automation could silence a room in use.

## Installation

1. In HACS, add `https://github.com/ajguerre1/ha-monolith-htp1` as a custom repository of
   category **Integration**.
2. Install **HA Monolith HTP1** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → HA Monolith HTP1**, then enter the
   processor's address. Repeat once per unit.

The address field accepts a pasted `http://` or `ws://` URL as well as a bare host.

### Give each unit a fixed address

**There is no discovery.** The HTP-1 advertises no mDNS or SSDP service, and its status
document carries no MAC address anywhere — so Home Assistant cannot follow a unit that DHCP
moves, and no amount of cleverness in the integration can change that. Give each processor a
DHCP reservation or a static address.

If a unit does move, **Settings → Devices & services → HA Monolith HTP1 → Reconfigure** updates
the address. The unit is identified by serial number, so pointing an entry at a *different*
processor is refused rather than silently re-targeting every entity in the room.

## Options

| Option | Default | |
|---|---|---|
| When turned off | Sleep | Sleep, Shut down, or Do nothing. |
| Volume limit (dB) | none | Refuses to *send* above this level. Does not change what the processor reports. |

Changing an option does not reload the entry, so a healthy connection is not dropped and no
entity blanks.

## Security

The unit exposes **no authentication and no TLS**, and no REST API. Anyone who can reach it on
the network can control it. Treat network access to the processor as equivalent to control of
it, and put it on a network where that is acceptable.

## Firmware

The protocol was verified live on firmware **1.13.3** and **2.1.1**; this integration was
measured against **2.1.2** on five units. The two families report different documents — 2.1.x
adds `channeltrim`, `dialnorm` and `shaker`, and 1.13.x has no video status block at all — so
every read is absence-tolerant and unreported features are simply not created.

Firmware 1.13.x is supported by that tolerance rather than by direct measurement here, since no
unit on hand runs it.

## Known limitations

- **No discovery, and no DHCP self-heal.** See above; the document carries no MAC.
- **No `media_player` transport controls.** The HTP-1 is a pre-processor. It does not play
  anything, and inferring "playing" from a decoded format would claim more than it tells us.
- **Status sensors are free text.** Real values include `5.2.2t` and `Native Dolby ATMOS`; any
  enumeration written today would be a bug on a firmware nobody has seen yet.
- **Dirac slots are addressed by index, not name**, because they are frequently unnamed and
  nothing stops two of them sharing a name.

## Troubleshooting

**"Could not reach that address"** — the processor is off the network, shut down (not asleep),
or the address is wrong.

**"The address answered but did not complete the connection"** — the unit accepts TCP on port
80 while it is still starting up. Wait about thirty seconds and try again. The integration
carries a 15-second handshake timeout for exactly this reason.

**Entities are unavailable** — the connection dropped; the client reconnects on a
2/4/8/16/30/60-second ladder with jitter. One log line per outage, one on recovery.

**Something looks wrong** — download diagnostics from the device page. They are redacted of
host, serial, unit name, input labels and Dirac slot names, so they are safe to paste into a
public issue.

## Development

```bash
pip install -r requirements-test.txt
pytest tests/ -v          # client and packaging tests; no Home Assistant needed
ruff check . && ruff format --check .
```

Tests are split deliberately. `tests/` imports no Home Assistant and runs anywhere, including
Windows. `tests/ha/` needs `pytest-homeassistant-custom-component` and therefore Linux, so it
runs in CI.

`tools/fake_htp1.py` speaks the real protocol with fault injection, including
`accept-tcp-no-upgrade` — the only way to prove the handshake timeout actually fires.
`scripts/probe_htp1.py` is a **read-only** probe for real hardware; it cannot write, and a test
enforces that.

Requirements, design and planning documents live under `docs/`. The design document is worth
reading before changing the client: most of what looks arbitrary in there — the tie rule on
volume rounding, the parse-failure budget, the write queue's debounce — is a defect that was
paid for once already.

## Credits

- [`jsoosiah/htp1-custom-controller`](https://github.com/jsoosiah/htp1-custom-controller) — a
  custom web UI for the HTP-1, and the most complete public description of the MSO document.
- [`ross/ha-monoprice-htp1`](https://github.com/ross/ha-monoprice-htp1) — an earlier Home
  Assistant integration for this processor, used as a reference.

## License

MIT — see [LICENSE](LICENSE).
