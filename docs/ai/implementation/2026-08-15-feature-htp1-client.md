---
phase: implementation
title: Implementation Guide
description: Technical implementation notes, patterns, and code guidelines
---

# Implementation Guide — `htp1-client`

Running record of what actually shipped, updated after each task. Task list and ordering live
in the planning doc.

## Task status

| Task | Status | Evidence |
|---|---|---|
| T1 fixtures and test harness | **done** | 20 tests pass on Windows with Home Assistant absent; ruff check + format clean |
| T2 `protocol.py` | **done** | 34 protocol tests + 2 package-hygiene tests; 56 total green; ruff clean |
| T3 `models.py` | **done** | 47 tests; 103 total green. A failing test found a floating-point tie defect — see below |
| T4 `mso.py` + `options.py` | **done** | 37 mirror tests + 20 option tests; 160 total green; ruff clean |
| T5 client: transport | **done** | 23 tests; 183 total green; slowest test 0.04 s. Two API warts raised at review and fixed |
| T6 client: read path | **done** | 17 tests; 200 total green. Budget guard demonstrated against a deliberately broken implementation |
| T7a client: queue, guard, interlock | **done** | 26 tests; 226 total green |
| T7b client: pending overlay, reconcile | todo | |
| T8 fake device | todo | |
| T9 integration tests | todo | |
| T10 probe script | todo | |
| T11 probe the five units (read-only, **gated on approval**) | todo | |
| T12 reconcile | todo | |

## Development Setup

```bash
pip install -r requirements-test.txt
pytest tests/ -v
ruff check . && ruff format --check .
```

No Home Assistant, no device, and no network are needed for anything up to T10. Verified: on
this dev box `import homeassistant` raises `ModuleNotFoundError` and the suite still runs.

## Code Structure

```
tests/
├── conftest.py            harness: HA detection, stub parents, fixture loaders
├── fixtures/
│   ├── mso_modern.json    firmware 2.x shape
│   ├── mso_legacy.json    firmware 1.x shape
│   ├── mso_sparse.json    two keys, nothing else
│   └── wire_samples.json  message-level corpus
├── test_fixtures.py       the fixtures are themselves tested
├── test_harness.py        the stub-import trick is itself tested
└── test_manifest.py       packaging contract (from M0)
```

## Implementation Notes

### T1 — fixtures and test harness

**The stub-parent-package trick.** `tests/conftest.py` tries `import homeassistant`. When that
fails, it registers module objects for `custom_components` and
`custom_components.ha_monolith_htp1` in `sys.modules`, each with a correct `__path__`, and sets
`collect_ignore_glob = ["ha/*"]`.

The point is not to tolerate the integration's `__init__.py` but to **bypass** it. Today that
file imports nothing; from M2 it imports Home Assistant, and without the stub every client test
would fail at import time on this machine. `test_harness.py` asserts the stub has no
`__file__`, which is what proves the real module never executed.

**Fixtures were written from scratch, not ported.** The Control4 driver's `tests/fixtures.lua`
also holds invented values, but regenerating closes risk R5 by construction instead of by
inspection. Only the *schema* was reused — path names and value domains, which are documented
and are not site data.

Deliberate differences between the two firmware fixtures, each of which some later test
depends on:

| Property | `mso_modern` | `mso_legacy` |
|---|---|---|
| `videostat` | present | **absent entirely** |
| Second-zone volume key | `secondaryVolume` | `secondVolume` |
| 2.x-only blocks | `channeltrim`, `dialnorm`, `shaker`, `lcvc` | none |
| `svronly` macros | present | absent |
| Unnamed Dirac slot | one with `name: ""` | one with **no `name` key at all** |
| `vpl` / `vph` | −50 / 0 | **−60 / −5** |
| `swVer` | `V2.1.1` | `V1.13.3` |

The two unnamed-slot shapes are different code paths in the mirror, so both exist and
`test_the_two_unnamed_slot_shapes_are_both_represented` keeps them that way. The differing
volume ranges are deliberate too: any code that hardcodes −50..0 fails against the legacy
fixture.

`mso_modern` also carries two properties the source-list logic will need: **duplicate visible
labels** (`h1` and `spdif1` are both "Media Player") and a **visible input with a blank label**
(`h4`).

### T2 — `protocol.py`

Pure codec: no I/O, no state, no clock. `parse_message` never raises, because a device we do
not control is on the other end and an exception there drops the link.

**`MALFORMED` and `UNKNOWN` are separate kinds, and the split is the design.** Both are
"we did not act on this", but they mean opposite things to the client above:

| Kind | Meaning | Consequence |
|---|---|---|
| `MALFORMED` | A verb we own carried an argument we could not decode — e.g. `mso {not json` | Counts against the parse-failure budget of 3 |
| `UNKNOWN` | Decoded cleanly, shape not one we act on — an unknown verb, bare JSON we do not recognise, an empty frame | **Free.** Ignored, logged at debug |

Conflating them fails in one of two directions: either newer firmware saying something novel
throttles a perfectly healthy connection, or genuine corruption never trips the cap that exists
to stop a `getmso` storm against a live unit.

**Bare-JSON classification** is a shape sniff, in this order: operations first (an array of
`{op, path}`, or a single unwrapped one), then a document if the object carries any of fifteen
known top-level MSO keys, else `UNKNOWN`. Guessing "document" from an arbitrary object would
let an unrelated payload wipe the mirror.

**`encode_change` raises rather than emitting anything questionable** — empty arrays and any
op that is not `replace`. Both are refusals to send, not runtime checks on incoming data: the
caller has the bug, and the consequence lands on a live processor.

### T3 — `models.py`

**The floating-point tie defect, found by a failing test rather than by review.**

The volume map was written exactly as designed — unrounded fraction out, half-down rounding
back to integer dB — and `test_ties_round_down_never_up` still failed, on 55%.

`0.55 * 50` is `27.499999999999996`, not `27.5`. So an input that is *mathematically* the tie
−22.5 dB arrives a hair above it, is no longer a tie, and rounds to −22: **one dB louder than
requested**, which is the single direction the tie rule exists to forbid.

`fraction_to_db` now snaps the intermediate to nine decimal places before rounding. Measured
across five plausible ranges rather than assumed:

| Range | Exact ties | Wrong without the snap |
|---|---|---|
| −50..0 | 50 | **1** (55%) |
| −80..+10 | 10 | **1** |
| −90..0 | 10 | **1** |
| −127..0 | 1 | 0 |
| −60..−5 | 5 | 0 |

So it is rare, not widespread — my first instinct was that half of all ties would be affected,
and that was wrong. It is still worth the guard: which input is hit depends on the range,
`vpl`/`vph` are user-configurable per unit, and the error is always in the louder direction.

**The test was wrong too, and in the same way.** It detected ties with `math.isclose` but
asserted with `math.floor` of the float — tolerant detection, intolerant assertion. It now uses
`fractions.Fraction`, so a tie is identified exactly rather than approximately. Asking a float
whether it is a tie gets the wrong answer for precisely the inputs the test is about.

**Codecs are stateless.** They decode either wire shape and `matches()` reports which one
actually arrived. That is the HW-02 insurance: `/eq/tc` is declared boolean but unmeasured, and
a wrong declaration degrades to a log line rather than to a switch that silently does nothing.
The warn-once reporting lives in the mirror (T4), not here — a flag on a module-level codec
instance would suppress the warning across all five units after the first.

`decode` returns `None` for anything unreadable. Unreadable is not `False`: a control whose
value is unknown must report unknown rather than quietly claim to be off.

**Deferred deliberately.** The design lists `source_options`, `sound_mode_options` and
`dirac_slot_options` under `models.py`. They consume collections the mirror builds, so they
land with T4 rather than being designed here against a data shape that does not exist yet.

### T4 — `mso.py` and `options.py`

The mirror is a projection: ~30 tracked scalar leaves plus three collections (`inputs`,
`dirac_slots`, `upmix_visible`). Classification happens before any allocation, which is what
makes the `/status/raw` blob free — a dict lookup and at most three anchored regex matches.

**Container re-derivation is table-driven.** `_apply_container` walks `TRACKED_PATHS` for
entries beneath the prefix and resolves each relative pointer inside the value. There is no
per-container unpacking to drift, which matters because all eight subtrees behave identically.

**Absent stays unspecified.** A container replace only assigns leaves the value actually
mentions. The `/inputs` sample in `wire_samples.json` names three inputs out of twenty-one, and
`test_absent_keys_are_unspecified_not_cleared` proves the other eighteen survive. The single
exception is `apply_document`, which is a census.

**`_assign` compares before storing, and treats a never-seen field as `None`.** So setting an
absent field to `None` on the first document is not a change — otherwise every entity for every
field this firmware lacks would be woken on connect, across five units and ~50 panels.

**Codec-mismatch reporting lives here, not in `models.py`.** "Report once" is state, and a
warn-once flag on a module-level codec instance would suppress the warning across all five
units after the first. `mirror.mismatches` is a per-instance tuple.

#### `options.py` — a spec ambiguity found by a failing test

Two tests I wrote in the same file contradicted each other about what a **missing** `homevis`
means: one expected unmentioned modes to be hidden, the other expected them shown. Both could
not hold.

Resolved to **absent means visible**, as a single rule with no special case:

- Firmware 1.13.x omits `homevis` entirely, and there is no way to distinguish "this firmware
  does not report visibility" from "this mode is hidden".
- Defaulting to hidden empties the whole dropdown on that firmware. Defaulting to visible costs
  at worst one extra entry the user does not want.

The failure mode is asymmetric, so the tolerant default wins. The test that assumed otherwise
was the wrong one and now states the rule explicitly.

Other option rules, each fixing a visible defect: canonical order rather than dict order (a unit
reordering `/inputs` would otherwise reshuffle every dropdown on reconnect); the current value is
always injected (Home Assistant renders a blank selector otherwise, and an input can be selected
while invisible); and **every** member of a label collision is suffixed, not just the later one,
which would reintroduce the order dependence.

Dirac slots are labelled by wire index — `"0 - Reference"`, `"2 - Slot 2"` — so the number the
user sees is the number `/cal/currentdiracslot` uses, duplicates are unique for free, and
resolution is positional rather than by name.

### T5 — `client.py`, transport half

The first module with a socket, a task and a clock. Tested through an injected fake session at
the `ws_connect` seam — the same seam Home Assistant's managed session plugs into — rather than
by mocking aiohttp internals. Nothing sleeps: backoff delays go to an injected recorder, and the
connect-timeout test uses a 0.02 s deadline while `DEFAULT_CONNECT_TIMEOUT` stays 15 s with its
own test. The whole transport suite runs in 0.08 s.

**The connect timeout spans the handshake, not just the TCP connect.** `_HangingConnection` in
`tests/fakes.py` reproduces the exact Control4 defect: a connection that is accepted and never
upgraded. Without the deadline nothing internal can leave the connecting state.

**`async_start` makes one attempt.** On failure it tears down and raises, having started no
ladder — `test_start_makes_one_attempt_and_raises` asserts exactly one `ws_connect` call. The
supervisor, and therefore indefinite reconnection, begins only after a first document.

**A reconnect re-sends `getmso`.** State after a gap cannot be assumed unchanged; the front
panel may have moved things while the link was down.

#### Two API warts, raised at review and fixed before T6

1. **`note_failure()` and `backoff_schedule()` were public because tests needed them.** Neither
   had a production caller, and API shaped by tests tends to stay that way. Both are now
   private; the tests reach through the underscore, which is honest about what they are.
   `backoff_index` was dropped entirely — when diagnostics wants it in M2 it can come back with
   a real caller.
2. **`backoff_schedule()` consumed the client's RNG.** It advanced a *local* index copy but drew
   from `self._rng`, so previewing the ladder changed the delays a real reconnect would use.
   It now snapshots the generator with `getstate()` and restores it in a `finally`.

The second matters more than it first appears. The obvious future caller is a diagnostics dump —
"next retry in about N seconds" is exactly what belongs in one — and a preview that perturbs the
thing it previews is the kind of trap that is only ever found by someone debugging something
else. `test_previewing_the_ladder_has_no_side_effect` pins both halves: previewing twice gives
the same answer, and the preview matches what `_next_delay()` actually returns. Confirmed the
test would have failed against the old implementation rather than assuming it.

The resulting public surface is exactly what the layers above need:
`allow_writes`, `async_start`, `async_stop`, `connected`, `host`, `mirror`, `reconnecting`,
`url`.

#### A repeat of an earlier mistake, caught by its own test

`test_the_module_never_seeds_the_global_random_generator` first failed — on the module's own
docstring, which contains the words `random.seed()` as a warning. Exactly the false positive
the AST approach was introduced for in T2, made again with a substring check. Now by AST, with
`test_the_call_detector_actually_detects` proving the detector can fail.

### T6 — `client.py`, read path

**The parse-failure budget has three reset sites and one forbidden one.**

| Where | Resets? | Why |
|---|---|---|
| A decodable message arrives | **yes** | The cap counts *consecutive* failures; one good reply means the unit is fine |
| `_connect` | **yes** | A fresh connection is a fresh chance; old failures belong to a dead conversation |
| `async_refresh` | **yes** | A deliberate re-request, from the reconcile watchdog or a manual reload |
| The error path's own re-read | **NO** | Resetting here zeroes the counter on every failure and restores the storm the cap exists to prevent |

The last row is enforced by calling `_request_document()` directly rather than `async_refresh()`,
with a comment at the call site saying why. Measured against a deliberately broken build:

```
reset only on deliberate re-request : 2 re-reads for 10 bad frames   (capped)
reset inside the error path's retry : 10 re-reads for 10 bad frames  (storm)
```

Without *any* reset the cap has no way back at all — a client whose first document failed three
times would sit on a live socket, mute, forever. Both extremes were real Control4 defects.

**`error` frames and unknown shapes cost nothing.** An `error "bad-verb"` means the unit
rejected something *we* said; there is nothing to re-read and the connection survives. An
unrecognised shape decoded fine. Charging either against the budget would throttle a healthy
connection, which matters given assumption A5 — newer firmware emits payloads we have never
seen.

**Listeners get their own unsubscribe.** `add_listener` returns the callable, so a Home
Assistant entity passes it straight to `async_on_remove` and cannot leak a subscription. A
listener that raises is logged and skipped: the `except Exception` there is deliberately broad,
because an entity blowing up in its callback must not cost the connection for every other
entity on the unit.

**A fake-only bug, worth noting.** `test_reconnecting_restores_the_budget` failed first time,
and the fault was in `tests/fakes.py`, not the client: closing a held-open socket left
`receive()` waiting on a gate nobody would set again, so the test hung rather than exercising
the reconnect. A fake that cannot disconnect makes every reconnect test vacuous.

### T7a — `client.py`, write path: queue, guard, interlock

Split from T7b deliberately: the planning doc flagged T7 as the densest task and said to split
the reconcile watchdog out rather than rush it.

**Writable paths are an allowlist, not "everything tracked".** `/status/*`, `/videostat/*` and
`/versions/*` are what the unit reports about itself. The unit rejects an entire `changemso` if
one operation targets a member it does not have, so a single bad path silently voids every other
write coalesced into the same flush — which makes a permissive check actively dangerous rather
than merely untidy.

**The guard compares against queue-then-mirror.** Comparing against the mirror alone would let a
second write of an already-queued value through, because the mirror does not learn the value
until the unit echoes it back. Sent-but-unconfirmed values need the pending overlay, which is
T7b — the scope boundary is stated in the test module's docstring so nobody reads the guard as
complete.

**Values are encoded at flush, not at queue time.** The queue holds Python values so the guard
can compare like with like; `/loudness` becomes `"on"` only on the way out.

**The queue is discarded in `_teardown`**, which every disconnect path already runs through, so
there is no route that reconnects with stale operations still pending.

### Patterns

- **Test names are full sentences** describing behaviour, and each module docstring names the
  defect the suite guards against. This is what stops a later reader "simplifying" a guard away.
- **Fixtures are tested.** Three fixtures that are quietly the same shape would prove nothing
  about firmware skew, so their differences are asserted rather than assumed.
- **Guards prove they can fail.** The Home Assistant import detector has its own test against
  synthetic violations, including a docstring mention that must not trip it. A green assertion
  from a detector that never fires is worse than no assertion, because it reads as coverage.
- **Detection by AST, not by grep**, wherever source is being inspected — this package
  discusses Home Assistant constantly in prose.

## Integration Points

None yet. T1 touches no production code — `custom_components/ha_monolith_htp1/` is unchanged
since M0.

## Error Handling

Not applicable to T1. From T2 the client's `Htp1Error` hierarchy applies.

## Performance Considerations

Fixture loaders are `scope="session"`, so each JSON document is parsed once per run. The suite
completes in ~0.04 s, which is the point of keeping Home Assistant out of it.

## Security Notes

**This repository is public, and a real `mso` document is site data** — it carries the owner's
unit name, input labels, Dirac slot names and serial number.

`test_fixtures_carry_no_site_data` enforces that every input label and Dirac slot name in the
committed fixtures comes from a small invented vocabulary, that serials start with `TESTSN`,
and that unit names are obviously synthetic. A future "let me just paste a real capture in"
fails the suite rather than passing review unnoticed.

Deviation from the original plan, recorded: fixtures were **regenerated rather than ported**, at
the user's direction, which removes the question of inherited site data instead of answering it
by inspection.
