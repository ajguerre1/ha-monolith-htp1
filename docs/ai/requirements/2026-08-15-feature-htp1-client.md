---
phase: requirements
title: Requirements & Problem Understanding
description: Clarify the problem space, gather requirements, and define success criteria
---

# Requirements & Problem Understanding — `htp1-client`

The vendored protocol client for the Monoprice Monolith HTP-1, under
`custom_components/ha_monolith_htp1/htp1/`. Milestone M1.

## Problem Statement

**What problem are we solving?**

The integration needs to talk to an HTP-1, and nothing usable exists to do it with.

- The processor's only control path is a WebSocket at `ws://<host>/ws/controller` speaking a
  bespoke `verb[space]JSON` protocol. There is no REST API, no published Python client, and no
  library on PyPI.
- Adding one as a runtime dependency is not an option: `manifest.json` must keep
  `requirements: []`, because a `git+https` requirement is refetched on every Home Assistant
  restart (`is_installed()` returns False for URL requirements).
- The obvious reference implementation, `ross/ha-monoprice-htp1`, documents that it "will
  sometimes lose the ability to talk to the device after a month or two" — so copying its
  transport would import a known defect.
- We already own a correct implementation of this protocol in Lua, from the Control4 Monolith
  HTP-1 driver, whose adversarial reviews caught six classes of bug. That knowledge is the
  asset; rewriting it from scratch in Python would discard it.

**Who is affected?** Everything above this layer. Five processors, ~20 entities each, feeding a
Home Assistant instance that drives ~50 wall panels.

**Current situation:** no client exists. M1 builds it.

## Goals & Objectives

**Primary goals**

1. A correct, fully offline-testable client that owns the socket, the protocol, and the
   mirrored device state — and imports no Home Assistant.
2. Port every hard-won invariant from the Control4 driver rather than rediscovering it.
3. Be safe against a live, occupied house **by construction**, not by discipline.

**Secondary goals**

4. A read-only probe script that answers the outstanding hardware questions (HW-02, HW-03,
   HW-04, HW-07) before M2 encodes assumptions about them.
5. A fake device with fault injection, so failure paths are testable without unplugging
   anything.

**Non-goals (explicitly out of scope for M1)**

- Any Home Assistant code — no entities, no config flow, no coordinator. That is M2/M3.
- Writes to `/svronly` macros, `/peq`, `/speakers`, `/sgen`, `/channeltrim`, `/CEC`,
  `/personalize`. The client tracks only what the v1.0 entity set needs.
- Discovery. The unit advertises no mDNS or SSDP; the host is supplied by the caller.
- Reconnect *policy* decisions that belong to Home Assistant, such as how long to retry before
  giving up. The client reconnects indefinitely; HA owns setup-time retry.

## User Stories & Use Cases

The "users" of this milestone are the M2/M3 integration code and the developer.

- As **the integration**, I want one object that stays connected and tells me when something
  changed, so entities never poll and never manage a socket.
- As **the integration**, I want to write a value by JSON pointer and have redundant, rapid and
  same-path writes collapsed for me, so a volume slider drag does not become a message storm.
- As **the integration**, I want a missing path to disable one feature rather than raise, so a
  1.13.x unit loses its video sensors and keeps everything else.
- As **the developer**, I want to run the whole suite on Windows with no Home Assistant and no
  hardware, so the inner loop is seconds.
- As **the developer**, I want a client that *cannot* write unless I explicitly enable it, so a
  scratch script cannot change the volume in an occupied room.
- As **the developer**, I want to prove the 15 s handshake timeout fires, which requires a
  server that accepts TCP and never upgrades.

**Edge cases that must be handled, not merely noted**

- A message that is not decodable at all; three in a row; and a fourth.
- A `msoupdate` carrying a single unwrapped op instead of an array.
- A payload that is bare JSON with no verb (newer firmware).
- A container `replace` on `/status`, `/cal`, `/inputs`, `/upmix`, `/versions`, `/videostat`,
  `/cal/slots`, `/svronly`, where every tracked leaf beneath must be re-derived.
- A `/cal/slots` entry whose `name` is `""`, and one where the key is absent entirely.
- A unit that accepts TCP on :80 but never completes the WebSocket handshake.
- A write whose confirming push never arrives.
- A disconnect with writes still queued.

## Success Criteria

Each invariant below is an acceptance criterion with a named test. **M1 is done when every row
has a passing test**, not when the code looks right.

| # | Acceptance criterion | Test |
|---|---|---|
| AC-01 | Connect/handshake is abandoned after 15 s | `test_handshake_timeout_fires_when_the_socket_never_upgrades` |
| AC-02 | A write equal to the current mirrored value is not sent | `test_600_identical_volume_writes_send_nothing` |
| AC-03 | dB↔fraction round-trips exactly for every integer dB, over several `(vpl, vph)` pairs | `test_every_db_survives_a_round_trip` |
| AC-04 | Every exact `.5` tie rounds **down** | `test_ties_round_down_never_up` |
| AC-05 | Writes coalesce by path within the 50 ms window; last value wins; one `changemso` per flush | `test_writes_to_one_path_coalesce_to_the_last_value` |
| AC-06 | An empty op array is never sent | `test_a_flush_with_nothing_to_say_sends_nothing` |
| AC-07 | Only `replace` ops are emitted | `test_only_replace_operations_are_emitted` |
| AC-08 | An unconfirmed write is rolled back and re-read after 2 s; the timer re-arms per flush | `test_an_unconfirmed_write_is_rolled_back`, `test_reconcile_deadline_is_per_flush` |
| AC-09 | Consecutive parse failures stop at 3; the error path's own retry does **not** reset the budget; a deliberate re-request does | `test_parse_failures_stop_at_three`, `test_the_error_path_retry_does_not_reset_the_budget`, `test_a_deliberate_refresh_restores_the_budget` |
| AC-10 | The write queue is discarded on disconnect, never replayed | `test_the_queue_does_not_survive_a_disconnect` |
| AC-11 | Backoff follows 2/4/8/16/30/60 s with ±20 % jitter from a per-client RNG; two clients with different seeds diverge; no global RNG is touched | `test_backoff_ladder_and_jitter_bounds`, `test_two_clients_do_not_reconnect_in_lockstep`, `test_module_never_calls_random_seed` |
| AC-12 | A missing path disables its feature and raises nothing; the sparse fixture loads | `test_a_sparse_document_loads_without_error` |
| AC-13 | A container replace re-derives every tracked leaf beneath it, for all eight container paths | `test_container_replace_rederives_every_leaf` |
| AC-14 | `/cal/slots` always yields six positional rows, for empty-name and absent-name shapes alike | `test_slots_are_always_six_rows` |
| AC-15 | A message is split on the **first** space only | `test_a_payload_containing_spaces_is_not_split_further` |
| AC-16 | `error "bad-verb"`, bare JSON, and unknown shapes are survived, never raised | `test_the_client_survives_everything_the_unit_can_say` |
| AC-17 | A no-op push produces an empty change set and notifies nobody | `test_a_push_that_changes_nothing_notifies_nobody` |
| AC-18 | A read-only client refuses every write before sending a byte | `test_a_read_only_client_refuses_every_write` |
| AC-19 | The package imports no Home Assistant | `test_the_client_package_imports_no_home_assistant` |

**Performance:** applying a `msoupdate` for an untracked path (e.g. `/status/raw/...`) must not
walk the document — a dict lookup and at most two anchored regex matches. The ~38 KB `mso`
document collapses to ~35 tracked leaves plus three collections.

**Coverage target:** every module in `htp1/` exercised; the `mso` applier and the dB math are
the two where a silent wrong answer is most likely, so both get exhaustive table-driven tests.

## Constraints & Assumptions

**Technical constraints**

- **Zero Home Assistant imports** in `htp1/`, and **zero runtime dependencies** beyond
  `aiohttp`, which Home Assistant already ships. `manifest.json` stays `requirements: []`.
- The `aiohttp.ClientSession` is **injected**, never created by the client, so the integration
  can hand it HA's managed session while tests hand it a throwaway.
- Python 3.13+ / ruff `target-version = "py313"`. Local dev runs 3.14.5; CI runs 3.13.
- `tests/` must import no Home Assistant so it runs on Windows.
- `aiohttp`'s `ws_connect(heartbeat=N)` derives its pong deadline as `N/2` and exposes no
  second knob, so the Control4 driver's 30 s ping / 10 s pong pair is **not expressible**. We
  use `heartbeat=30.0` → 15 s pong deadline, 45 s worst-case half-open detection. Documented,
  not hidden.

**Safety constraints**

- Five processors are live in an occupied home. **The client is read-only by default**
  (`allow_writes=False`); the integration opts in explicitly. Probe and capture scripts never
  do, so they are read-only by construction.
- Reading is provably passive: an idle connection sent zero bytes over 90 s, and the unit
  serves concurrent controller connections independently.
- Never `/powerAction: "reboot"` outside a deliberate agreed test.

**Privacy constraints**

- A real `mso` document is site data — it carries unit name, input labels, Dirac slot names and
  serial. Fixtures are invented or scrubbed. Raw probe output goes to gitignored
  `scripts/output/`. The probe prints a **scrubbed** summary by default.

**Assumptions** (each traceable to a live observation on firmware 1.13.3 and 2.1.1)

- A1. The unit pushes `msoupdate` on every change from any source, so polling is unnecessary.
- A2. The unit answers WebSocket PING with PONG, so keepalive belongs at the transport.
- A3. Junk input yields `error "bad-verb"` and the connection survives.
- A4. `/volume` is integer dB clamped to `[cal.vpl, cal.vph]`, both user-configurable.
- A5. Newer firmware sometimes emits bare JSON with no verb prefix. *(Inherited from a 2026-07
  fix in `ross/ha-monoprice-htp1`; not independently observed by us — treated as a shape to
  tolerate, not a behaviour to rely on.)*

## Questions & Open Items

### Resolved during this phase

**Q1 — Where does the "already there" guard live?** *(A contradiction in the approved plan: its
architecture section put the guard in the coordinator, while its verification section tested it
at the client.)*

**Resolved: the client owns the guard.** The client is the only object holding both the current
mirrored value and the write queue, which is exactly what the guard compares. Putting it there
makes it universal across all ~20 entities instead of something each command path must
remember, and it is testable with no Home Assistant. The coordinator keeps *semantic*
translation — fraction→dB, the power-off action choice, the lip-sync dual write, the
max-volume ceiling — which genuinely needs config entry options and therefore cannot live here.

**Q2 — Write safety.** Resolved: read-only by default, `allow_writes=True` is an explicit
opt-in. AC-18.

**Q3 — Probe timing.** Resolved: `scripts/probe_htp1.py` ships in M1 and is run read-only
against all five units at the end of the milestone, closing HW-02/03/04/07 before M2 begins.

### Deferred, with owner

- **HW-01** (does the network stack survive `powerIsOn: false`) and **HW-06** (lip-sync dual
  write) require writes and wait for M4 on the lab unit. M2 ships with the safe assumption
  recorded as a single constant.
- **A5** (bare-JSON payloads) is inherited, not observed. The probe's observe mode should
  record whether any of the five units ever emits one. If none do over a long observation, the
  tolerance stays anyway — it costs nothing — but the comment should say it is unconfirmed.

### Open

- None blocking. M1 can proceed.
