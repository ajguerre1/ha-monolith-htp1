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
| T3 `models.py` | todo | |
| T4 `mso.py` | todo | |
| T5 client: transport | todo | |
| T6 client: read path | todo | |
| T7 client: write path | todo | |
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
