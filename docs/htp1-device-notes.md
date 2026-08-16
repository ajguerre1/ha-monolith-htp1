# Monoprice Monolith HTP-1 — device notes

What this processor actually does, as opposed to what its document suggests it does.

Measured against five live units on firmware 2.1.2, plus a prior driver verified on 1.13.3 and
2.1.1. Every number here was observed, not inferred. If you are writing anything that talks to
an HTP-1 — this integration or your own — the traps below each cost something to find.

**Core principle: the unit's confirmed value is the truth.** It echoes every change from every
source — front panel, web UI, another controller — so there is never a reason to display what
you asked for instead of what it did. Optimism belongs in a separate overlay that a confirming
push deletes, never in the mirror itself.

## Transport

`ws://<host>/ws/controller`, port 80. **No auth, no TLS, no REST API, no mDNS, no SSDP.**

Text frames of `verb[space]JSON`, **split on the first space only** — the payload contains
spaces.

| Send | Get |
|---|---|
| `getmso` | `mso {…}` — ~41 KB on the wire, ~47.5 KB re-serialised, 2963 paths on 2.1.2 |
| `changemso [ops]` | RFC 6902, `replace` only |
| anything else | `error "bad-verb"`, **and the connection survives** |

Unsolicited: `msoupdate [ops]` on every change from any source. Sometimes a **single unwrapped
op** instead of an array, and on newer firmware sometimes **bare JSON with no verb at all**.

An idle connection sent **zero bytes over 90 seconds**. This is a push device; any poll interval
is pure waste. Concurrent controller connections are served independently, so reading never
fights the web UI or another controller.

## The trap that costs a physical trip

**`/powerAction` has two ways of going quiet and only one is recoverable.**

| Value | Front panel | Network | Recoverable remotely |
|---|---|---|---|
| `"sleep"` | off | **stays up** | yes |
| `"off"` | off | **gone** | **no** |

`"off"` is the web UI's *Shutdown*. Measured: no answer on port 80 within ten seconds, still
silent after four minutes, started only from the front panel. Map a media player's `turn_off`
to `"sleep"`. Never reach `"off"` from a service call — put it behind a separately-enabled
control, because the entity registry's enable step is the only real confirmation gate.

`fastStart: "on"` is **not** evidence that the network survives power-off. It governs how
quickly the unit wakes from standby and whether CEC auto-power-on works, and says nothing about
shutdown. Reading it the other way is what produced the mistake above.

When testing reachability, open a **fresh** socket. A held one looks alive from your side for
minutes, and the question that matters is whether a *restarted* client can reach the unit.

## Volume

Absolute integer dB over the unit's own `/cal/vpl`..`/cal/vph`. Measured −50..0 on all five
units, but **they are user-configurable — never hardcode them.**

Two rules, each of which was a real defect:

- **Round half DOWN**: `ceil(x - 0.5)`, never Python's `round()`, which is banker's rounding.
  Over −50..0 every odd percentage lands exactly on a half-dB, so the tie rule decides a large
  share of all inputs — and volume must land quieter than asked, never louder.
- **Snap before rounding.** `0.55 * 50 == 27.499999999999996`, which rounds *up* and defeats the
  tie rule. Round the product to ~9 decimals first.

Derive the 0–1 level from the **confirmed** dB, unrounded. Converting through an integer
percentage is lossy: over −127..0 it round-trips wrong 27 times in 128, and the first failure
returns a value one dB **louder** than asked.

There is no relative volume verb. A step is read-modify-write, in whole dB rather than in
fractions.

## Writing

- **"Already there" guard before every write.** Without it, a held volume ramp rewrote the same
  dB ~600 times in ten seconds.
- **Queue with a ~50 ms debounce, coalesced by path**, flushed as one `changemso`.
- **Never send an empty op array.** **`replace` only** — a stored `test` replayed as a `replace`
  would *execute*, and an `add` against a missing member makes the unit reject the whole message.
- **Discard the queue on disconnect.** Replaying it applies a stale command minutes later.
- **Re-arm the reconcile timer per flush.** Inheriting an older deadline gives a later write
  less than its full grace period.

## Absence and asymmetry

The document is not uniform, and 1.13.x is not 2.1.x.

- **No MAC address anywhere.** `/network/eth0` carries `dhcp`, `addr`, `mask`, `gw` and nothing
  else, and the last three are empty strings. The only `*mac*` matches are `/inputs/*/macro`.
  **DHCP self-heal is therefore not buildable** — do not imply one; recommend a reservation.
- **`/eq/tc` is a bool while `/loudness` and `/bassenhance` are `"off"`/`"on"` strings.** Declare
  a codec per path and warn once on a mismatch rather than guessing from a neighbour.
- **1.13.x has no `videostat` block at all.** A missing path must disable the feature that needs
  it, not raise.
- **Dirac slots are usually unnamed** — six rows, zero names on all five units here. Build
  options labelled by index (`0 - Slot 0`) and resolve the current slot **by index**. Resolving
  by name matches the wrong slot immediately, and nothing stops two slots sharing a name.
- **`/status` and `/videostat` do not stop when the unit sleeps.** A sleeping unit still reported
  `Dolby Surround` and `5.1.2`, and pushed a listening-format change twice in twenty seconds.
  Blank signal readings when the unit reports itself off — it is honest, and it stops that churn
  from reaching anything downstream.
- **Unread fields are padded with dashes** whose width follows the field: `--`, `---`, `-----`.
  Test for *nothing but* dashes and spaces, so a real `1920x1080p-60` survives.
- **Lip sync lives in two places and the unit pairs neither direction.** Writing `/cal/lipsync`
  alone moved it 0 → 120 while all 21 inputs stayed at `delay: 0`. Write `/cal/lipsync` and
  `/inputs/<current>/delay` together, in one message.

## Common mistakes

| Mistake | Consequence |
|---|---|
| `turn_off` → `/powerAction: "off"` | The unit leaves the network. Someone walks to it |
| Reading `fastStart: "on"` as "network survives power-off" | The above, with a confident rationale attached |
| Testing reachability on the socket you already hold | Half-open connection reads as healthy for minutes |
| `round()` instead of `ceil(x - 0.5)` | Banker's rounding; volume lands *louder* than asked |
| Rounding without snapping first | `0.55 * 50 = 27.4999…` rounds up and defeats the tie rule |
| Converting volume through an integer percentage | 27 of 128 dB values round-trip wrong |
| Hardcoding −50..0 | Wrong on any unit whose owner changed the range |
| No "already there" guard | ~600 identical writes from one ten-second volume hold |
| Splitting the frame on every space | Payload truncated at the first space inside the JSON |
| Assuming `msoupdate` is always a wrapped array | Missed updates: it is sometimes one bare op, sometimes verbless JSON |
| No connect/handshake timeout | The unit accepts TCP on :80 before `/ws/controller` is live; the client wedges forever |
| Resetting the parse-failure budget inside the error path's own retry | Unthrottled `getmso` storm against a live unit |
| `random.seed()` for backoff jitter | Mutates global state for the whole process; two instances reconnect in lockstep |
| Resolving the Dirac slot by name | Six empty names; picks the wrong calibration |
| Building the source list from dict order | JSON key order is not a contract; every dropdown reshuffles on reconnect |
| Omitting the current input because it is invisible | The frontend dropdown renders blank |
| Enumerating `/status` values | Real values include `5.2.2t` and `Native Dolby ATMOS` |
| Showing `/status` while the unit sleeps | A dark processor announces a soundtrack it stopped playing |
| Writing `/cal/lipsync` alone | The unit's own display disagrees, and the value is lost on the next input switch |
| Treating `error "bad-verb"` as fatal | Needless reconnect; the connection is fine |

## Home Assistant specifics this device forces

- **`iot_class: local_push`**, `update_interval=None`, driven by `async_set_updated_data`. Push
  mode never enters `_async_refresh`, so the "reconnected" log line is yours to emit — capture
  `was_down` before you publish.
- **`coordinator.data` is the same mutable mirror every time.** Its identity never changes;
  never compare it against a previous value.
- **Key entity `unique_id` on the entry id, not the host or serial.** The entry's own unique_id
  can then self-heal without orphaning twenty entities. The integration this replaced keyed
  entities on the host, so a DHCP move orphaned them.
- **Gate state writes at three layers** — mirror assignment, the change set, and an entity
  snapshot tuple including `available`. A push that moves nothing must produce no state write.
- **`config_entries/remove` is REST** (`DELETE /api/config/config_entries/entry/<id>`), not a
  WebSocket command.
- **A large installation's device registry can exceed aiohttp's 4 MB frame limit.** Raise
  `max_msg_size` on `ws_connect`.
- **To prove no state write happened, assert on `last_reported`, not `last_updated`.** An
  identical-value write leaves `last_updated` alone — which is exactly the case you are testing.

## Working on real hardware

`scripts/probe_htp1.py` is read-only, produces a scrubbed digest, cannot write, and a test
enforces that. `tools/fake_htp1.py` speaks the real protocol with fault injection;
`accept-tcp-no-upgrade` is the only way to prove the handshake timeout fires.

**Any script that writes to a real unit must restore in a `finally`, and must not be able to die
of its own logging.** One here raised `UnicodeEncodeError` from a `print` between the write and
the restore, and left a unit holding a changed value.
