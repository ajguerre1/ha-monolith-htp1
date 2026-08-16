---
phase: testing
title: Testing Strategy
description: Define testing approach, test cases, and quality assurance
---

# Testing Strategy — `htp1-client`

## Test Coverage Goals

- **100 % of `htp1/`.** Every module is reachable with no Home Assistant and no hardware, so
  there is no honest excuse for a gap.
- Every acceptance criterion AC-01..AC-19 in the requirements doc maps to a named test below.
  An AC with no passing test is an open AC.
- Test names are full sentences describing the behaviour, and each module docstring states the
  defect the suite guards against. Most of these defects are real ones from the Control4
  driver, and the docstring is what stops someone "simplifying" the guard away later.
- No Home Assistant import anywhere in `tests/` — it must run on the Windows dev box.

## Unit Tests

### Fixtures and harness (T1) — **complete**

Added during implementation; not foreseen when this document was first written. The fixtures
are ground truth for every later test, so they are tested themselves.

- [x] `test_all_three_documents_load`
- [x] `test_modern_and_legacy_differ_in_firmware_shape` — `videostat` present vs absent,
      `secondaryVolume` vs `secondVolume`, `V2.x` vs `V1.x`
- [x] `test_both_documents_carry_exactly_six_dirac_slots`
- [x] `test_the_two_unnamed_slot_shapes_are_both_represented` — `name: ""` in modern, `name`
      key absent in legacy. Different code paths; covering only one lets the other regress
- [x] `test_modern_carries_a_status_raw_blob_that_must_be_ignored`
- [x] `test_modern_carries_duplicate_input_labels` — the source list has to disambiguate
- [x] `test_modern_carries_a_visible_input_with_a_blank_label`
- [x] `test_sparse_is_genuinely_sparse` — exactly two keys, or it stops testing anything
- [x] `test_wire_samples_cover_every_shape_the_unit_can_emit`
- [x] `test_wire_samples_include_a_container_replace_for_every_container_path` — all eight
- [x] `test_fixtures_carry_no_site_data` — parametrised over both documents. The repo is public
- [x] `test_the_vendored_package_is_importable_without_home_assistant`
- [x] `test_the_parent_packages_are_stubbed_when_home_assistant_is_absent` — asserts the stub
      has no `__file__`, i.e. the real `__init__.py` was bypassed rather than merely tolerated

*Evidence:* 20 tests pass on Windows with `import homeassistant` raising `ModuleNotFoundError`.

### `protocol.py` — the wire codec

- [ ] `test_a_payload_containing_spaces_is_not_split_further` — `mso {"unitname":"a b c"}`
      parses with the value intact (AC-15)
- [ ] `test_a_verb_with_no_argument_parses` — bare `getmso`
- [ ] `test_parse_never_raises` — table-driven over ~40 malformed inputs: empty string, verb
      only, trailing space, invalid JSON, JSON `null`, a lone `[`, non-UTF8-ish text
- [ ] `test_error_frames_are_recognised_and_survivable` — `error "bad-verb"` (AC-16)
- [ ] `test_classify_bare_recognises_a_document` — bare JSON object with document shape
- [ ] `test_classify_bare_recognises_an_op_array_and_a_single_op`
- [ ] `test_classify_bare_drops_anything_else` — returns None rather than guessing
- [ ] `test_encode_change_refuses_an_empty_op_list` — raises, never emits `[]` (AC-06)
- [ ] `test_only_replace_operations_are_emitted` (AC-07)
- [ ] `test_encoded_change_is_one_message_with_all_ops`

### `models.py` — value semantics

- [ ] `test_every_db_survives_a_round_trip` — **the highest-value test in the suite**. For every
      integer dB across `(-50, 0)`, `(-80, 10)`, `(-127, 0)` and the degenerate `vph <= vpl`,
      `fraction_to_db(db_to_fraction(db)) == db` (AC-03). The `(-127, 0)` case is the one that
      matters: it has 128 dB values, so it fails outright if the fraction is ever rounded to an
      integer percentage — 27 failures, the first returning one dB *louder* than requested
- [ ] `test_the_fraction_is_never_quantised` — asserts `db_to_fraction` returns values a
      101-step percentage could not represent. This is the regression guard for Q4: it fails
      the moment someone "restores" the Control4 driver's `dbToPercent` behaviour
- [ ] `test_ties_round_down_never_up` — every exact `.5` input to `fraction_to_db`, both signs
      (AC-04)
- [ ] `test_round_half_down_is_not_bankers_rounding` — pins the difference from `round()`
      explicitly, so a future "simplification" fails here
- [ ] `test_a_degenerate_volume_range_does_not_divide_by_zero`
- [ ] `test_values_outside_the_range_are_clamped`
- [ ] `test_bool_codec_and_on_off_string_codec_round_trip`
- [ ] `test_a_codec_mismatch_is_reported_once` — declared bool, observed `"on"` (guards HW-02)

### `mso.py` — mirror and patch applier

- [ ] `test_the_three_fixtures_load_without_error` — modern, legacy, sparse (AC-12)
- [ ] `test_a_sparse_document_loads_without_error` — `{"volume": -10, "powerIsOn": false}` only
- [ ] `test_legacy_firmware_has_no_video_fields` — `videostat` absent, nothing raises
- [ ] `test_container_replace_rederives_every_leaf` — parametrised over all eight container
      paths (AC-13)
- [ ] `test_absent_keys_are_unspecified_not_cleared` — a partial `/inputs` replace must not
      wipe labels it did not mention
- [ ] `test_a_full_document_is_a_census` — the one case where members *may* be dropped
- [ ] `test_a_single_unwrapped_op_is_accepted`
- [ ] `test_slots_are_always_six_rows` — for the empty-`name` fixture *and* the absent-`name`
      fixture; both are different code paths (AC-14)
- [ ] `test_slot_indices_stay_aligned_with_currentdiracslot`
- [ ] `test_a_push_that_changes_nothing_notifies_nobody` — empty change set (AC-17)
- [ ] `test_the_change_set_is_exactly_the_fields_that_moved`
- [ ] `test_status_raw_is_never_walked` — a `/status/raw/...` push changes nothing and allocates
      nothing
- [ ] `test_unknown_paths_are_dropped_silently`

### `client.py` — transport, queue, timers

Driven by an injected fake transport and a controllable clock; no socket.

- [ ] `test_600_identical_volume_writes_send_nothing` — the guard, and the exact regression that
      motivated it: a held ramp once rewrote the same dB ~600 times in ten seconds (AC-02)
- [ ] `test_the_guard_compares_the_optimistic_value_not_the_confirmed_one` — with a write still
      unconfirmed, a second write of the same value is still suppressed. Comparing against the
      confirmed value instead would let a ramp through for up to 2 s and defeat the guard (Q5)
- [ ] `test_writing_while_disconnected_raises` — never queued for silent later delivery, which
      would reintroduce the stale-command bug from the other direction (AC-20, Q6)
- [ ] `test_a_read_only_client_refuses_every_write` — parametrised over every writable path,
      asserting nothing reached the transport (AC-18)
- [ ] `test_writes_to_one_path_coalesce_to_the_last_value` (AC-05)
- [ ] `test_writes_to_different_paths_share_one_changemso`
- [ ] `test_a_flush_with_nothing_to_say_sends_nothing` (AC-06)
- [ ] `test_an_unconfirmed_write_is_rolled_back` — after 2 s, discard and re-read (AC-08)
- [ ] `test_reconcile_deadline_is_per_flush` — a later write gets its full 2 s, not the
      remainder of the first write's window (AC-08)
- [ ] `test_a_confirming_push_cancels_the_reconcile`
- [ ] `test_parse_failures_stop_at_three` (AC-09)
- [ ] `test_the_error_path_retry_does_not_reset_the_budget` — **the subtle one**; resetting here
      rebuilds the unthrottled `getmso` storm (AC-09)
- [ ] `test_a_deliberate_refresh_restores_the_budget` — connect, reconcile, manual refresh
      (AC-09)
- [ ] `test_the_queue_does_not_survive_a_disconnect` (AC-10)
- [ ] `test_handshake_timeout_fires_when_the_socket_never_upgrades` (AC-01)
- [ ] `test_backoff_ladder_and_jitter_bounds` — 2/4/8/16/30/60, each within ±20 % (AC-11)
- [ ] `test_the_ladder_resets_on_a_successful_handshake`
- [ ] `test_two_clients_do_not_reconnect_in_lockstep` — different seeds diverge (AC-11)
- [ ] `test_module_never_calls_random_seed` — source-level assertion; a library that seeds the
      global RNG breaks every other integration (AC-11)
- [ ] `test_the_client_survives_everything_the_unit_can_say` — `error`, bare JSON, unknown
      verbs, empty frames (AC-16)
- [ ] `test_stop_is_idempotent_and_cancels_every_timer`

**State ownership — the pending overlay** (design §State ownership)

- [ ] `test_a_rollback_does_not_clobber_a_newer_push` — write A, a genuine push sets B before
      confirmation, reconcile fires. The result must be B, not the pre-write value. This is the
      bug that writing optimistic values into the mirror would cause, and the reason `_pending`
      is a separate overlay whose rollback is a deletion rather than a restore
- [ ] `test_a_confirming_push_notifies_nobody` — the value already shown optimistically produces
      an empty change set, so a confirmation round-trip costs zero entity writes
- [ ] `test_a_clamped_value_settles_on_the_units_answer` — the unit replies with a different
      value than requested; pending clears and listeners see the unit's number, not ours
- [ ] `test_an_optimistic_write_notifies_immediately` — what makes a slider feel instant

**Start and stop contract** (design §Start and stop contract)

- [ ] `test_start_makes_one_attempt_and_raises` — with `wait_for_first_document=True` a failure
      raises rather than entering the ladder, so Home Assistant owns setup retry and there are
      never two competing backoff loops
- [ ] `test_the_reconnect_ladder_only_starts_after_the_first_document`

**Write contract** (design §Write contract)

- [ ] `test_writing_an_unknown_path_raises` — the unit rejects an entire `changemso` if one op
      targets a missing member, so one bad path would silently void every coalesced write in
      that flush
- [ ] `test_writing_none_raises` — `None` is also the queue's "not queued" sentinel
- [ ] `test_writing_the_value_already_there_is_not_an_error` — returns successfully having sent
      nothing (AC-02), rather than raising

### `scripts/probe_htp1.py` — the read-only probe

- [ ] `test_the_probe_is_read_only_by_construction` — asserts the script never passes
      `allow_writes=True` and never calls a write method. Source-level, like
      `ha_somfy`'s `test_probe_safety.py`, because the guarantee must hold for a script nobody
      is unit-testing line by line (AC-21)
- [ ] `test_the_probe_summary_scrubs_site_data` — unit name, input labels, Dirac slot names and
      serial are redacted in the default summary. Raw output is opt-in and goes to gitignored
      `scripts/output/`

### Package hygiene

- [ ] `test_the_client_package_imports_no_home_assistant` — walks `htp1/*.py` and asserts no
      `homeassistant` import. This is the property that keeps the suite runnable on Windows
      (AC-19)
- [ ] `test_the_suite_installs_from_requirements_test` — asserts `aiohttp` is declared there
      rather than arriving through `pytest-homeassistant-custom-component`, which is unusable on
      the Windows dev box (Q7)

## Integration Tests

Against `tools/fake-htp1.py`, over a real loopback socket.

- [ ] `test_connect_getmso_and_first_document` — the happy path end to end
- [ ] `test_a_write_is_echoed_back_as_msoupdate` — the fake broadcasts applied ops, as the real
      unit does to every connected client
- [ ] `test_the_handshake_timeout_fires_against_accept_tcp_no_upgrade` — **the single most
      valuable fault in the set.** It is the only way to prove AC-01, and the defect it models
      wedged the Control4 driver permanently
- [ ] `test_a_trickled_document_reassembles` — one byte per write
- [ ] `test_an_ignored_ping_is_detected_and_reconnects`
- [ ] `test_a_never_confirmed_write_triggers_the_reconcile`
- [ ] `test_a_container_replace_from_the_wire_rederives_leaves`
- [ ] `test_garbage_frames_exhaust_the_budget_then_go_quiet`
- [ ] `test_a_document_without_a_serial_still_connects`
- [ ] `test_the_wrong_path_is_refused` — the unit closes 1008 on anything but `/ws/controller`

## End-to-End Tests

Against the five real processors, **read-only**, at the end of M1. Reading is provably passive:
an idle connection sent zero bytes over 90 s, and the unit serves concurrent controller
connections independently, so this does not disturb anyone using a room.

- [ ] Probe all five: connect, `getmso`, parse, disconnect — closes **HW-04** (real `vpl`/`vph`
      on each unit) and **HW-07** (the `/status` string vocabulary)
- [ ] Confirm the declared codec for `/eq/tc` on both firmware families — **HW-02**
- [ ] Search the document for a MAC address — **HW-03**; decides whether DHCP self-heal is even
      buildable
- [ ] Observe one unit for several minutes and confirm a front-panel change arrives as a push
      with no request sent
- [ ] Record whether any unit ever emits a bare-JSON payload (assumption A5, inherited from
      another project and not independently observed)

**Deferred to M4, lab unit only, one path per run, asking first:** HW-01 (does the network stack
survive `powerIsOn: false`) and HW-06 (lip-sync dual write).

## Test Data

**Fixtures** ported from the Control4 driver's `tests/fixtures.lua`, where they are already
invented rather than captured. `tests/fixtures/`:

| File | Shape |
|---|---|
| `mso_modern.json` | Firmware 2.x: `channeltrim`, `dialnorm`, `shaker`, `secondaryVolume`, full `status` **including a `status.raw` blob that must be ignored**, full `videostat`, six `cal.slots` with one deliberately **empty** name |
| `mso_legacy.json` | Firmware 1.x: `secondVolume`, `vu`, **no `videostat`**, **no `svronly`**, six slots with one where the `name` key is **absent entirely** |
| `mso_sparse.json` | `{"volume": -10, "powerIsOn": false}` — absence tolerance, total |
| `wire_samples.json` | Message corpus: op array; single unwrapped op; a container replace per container path; a `/status/raw/...` push; bare-JSON document; bare-JSON op array; `error "bad-verb"`; no-space message; empty string; JSON `null` argument; a value containing spaces; a 38 KB document |

**Privacy:** a real `mso` carries unit name, input labels, Dirac slot names and serial — site
data. Fixtures are invented; nothing captured from the five units is committed. Raw probe output
goes to gitignored `scripts/output/`.

**Mocks:** the device is faked at two levels — an in-process fake transport for `client.py`
timing tests (with a controllable clock, so no test sleeps), and `tools/fake-htp1.py` over a
real socket for integration tests. There is no mocking of `aiohttp` internals.

## Test Reporting & Coverage

```bash
pytest tests/ -v                       # everything in this milestone; no HA, no hardware
pytest tests/ --cov=custom_components/ha_monolith_htp1/htp1 --cov-report=term-missing
ruff check . && ruff format --check .  # CI runs both and stops at the first failure
```

CI additionally runs hassfest and the HACS action. Coverage gaps must be justified in this
document or closed; "hard to test" is not a justification for a module that takes an injected
transport and an injected clock.

## Manual Testing

No UI in this milestone. Manual validation is the read-only probe run above, whose output is
reviewed for: plausible `vpl`/`vph`, a firmware string, a serial, and no unexpected key types.

## Performance Testing

Not load testing — this device has one client and no throughput problem. Two properties are
asserted instead:

- [ ] `test_status_raw_is_never_walked` — an untracked push does no work
- [ ] `test_a_burst_of_writes_produces_one_message` — 100 writes inside one 50 ms window emit
      exactly one `changemso`

## Bug Tracking

`docs/ai/planning/backlog.md`: stable IDs, never reused, `open · in-progress · blocked · parked
· done`, priority H/M/L. **An item closes only with evidence** — a test name, a CI run number,
or a live observation. Severity is judged by what reaches the house: anything that can send an
unintended write to a live processor is the top band, ahead of any correctness bug that is
merely wrong on screen.
