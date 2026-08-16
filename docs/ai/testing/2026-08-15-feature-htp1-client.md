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

### `protocol.py` — the wire codec (T2) — **complete**

Names below are the ones that shipped; a few drifted from the originals as the behaviour got
sharper. 34 tests.

*Framing*
- [x] `test_a_payload_containing_spaces_is_not_split_further` — `mso {"unitname":"a b c"}`
      parses with the value intact (AC-15)
- [x] `test_a_verb_with_no_argument_parses` — bare `getmso`
- [x] `test_a_document_is_recognised`
- [x] `test_an_update_carries_its_operations`
- [x] `test_multiple_operations_survive_in_order`
- [x] `test_a_single_unwrapped_operation_is_accepted`
- [x] `test_an_untracked_path_still_parses` — filtering is the mirror's job, not the codec's

*Errors and the unrecognised*
- [x] `test_error_frames_are_recognised_and_survivable` — `error "bad-verb"` (AC-16)
- [x] `test_an_unknown_verb_is_unknown_not_malformed` — **the distinction that matters**: it
      decoded, so it must not spend parse budget
- [x] `test_undecodable_input_is_malformed` — the case that *does* count
- [x] `test_degenerate_frames_never_raise` — parametrised over empty, space-only, lone bracket
- [x] `test_parse_never_raises` — table-driven over 41 hostile inputs

*Bare JSON (newer firmware)*
- [x] `test_bare_json_document_is_recognised`
- [x] `test_bare_json_operation_array_is_recognised`
- [x] `test_bare_json_single_operation_is_recognised`
- [x] `test_bare_json_we_do_not_recognise_is_unknown_not_malformed`

*Encoding*
- [x] `test_get_mso_is_a_bare_verb`
- [x] `test_encode_change_produces_one_message_with_all_operations`
- [x] `test_encode_change_refuses_an_empty_operation_list` — raises, never emits `[]` (AC-06)
- [x] `test_only_replace_operations_are_emitted` (AC-07)
- [x] `test_encoded_messages_are_split_on_the_first_space_by_our_own_parser` — round-trip

*`normalise_ops`*
- [x] `test_normalise_ops_accepts_both_shapes` — parametrised: array, single op, multi, empty
- [x] `test_normalise_ops_rejects_anything_that_is_not_operations` — parametrised over 7 shapes

### `models.py` — value semantics (T3) — **complete**

47 tests.

*Rounding*
- [x] `test_round_half_down_sends_every_tie_downward` — parametrised, both signs
- [x] `test_round_half_down_is_not_bankers_rounding` — pins the difference from `round()`
      explicitly, so a future "simplification" fails here

*The volume map*
- [x] `test_every_db_survives_a_round_trip` — **the highest-value test in the suite**. Every
      integer dB across `(-50, 0)`, `(-80, 10)`, `(-127, 0)` (AC-03). The `(-127, 0)` case is
      the one that matters: 128 dB values cannot survive a 101-step percentage
- [x] `test_the_fraction_is_never_quantised` — the regression guard for Q4; fails the moment
      someone restores the Control4 `dbToPercent` behaviour
- [x] `test_the_fraction_is_a_float_between_zero_and_one`
- [x] `test_the_endpoints_map_to_zero_and_one`
- [x] `test_ties_round_down_never_up` (AC-04) — ties identified with `Fraction`, not floats,
      because asking a float whether it is a tie gets the wrong answer for exactly these inputs
- [x] `test_a_tie_arriving_with_floating_point_error_still_rounds_down` — **added during
      implementation**; see below
- [x] `test_values_outside_the_range_are_clamped`
- [x] `test_a_degenerate_volume_range_does_not_divide_by_zero` — parametrised over four
      nonsense ranges
- [x] `test_fractional_range_bounds_stay_inside_the_device_range` — `vpl`/`vph` need not be
      whole numbers; the result must still be an integer inside the reported range

*Codecs*
- [x] `test_the_boolean_codec_round_trips`
- [x] `test_the_on_off_string_codec_round_trips`
- [x] `test_each_codec_tolerates_the_other_wire_shape` — HW-02 insurance
- [x] `test_a_codec_returns_none_for_a_value_it_cannot_read` — unreadable is not `False`; a
      control must go unknown rather than silently claim to be off
- [x] `test_a_codec_can_tell_whether_the_wire_shape_matched_its_declaration`

*Versions*
- [x] `test_the_av_controller_version_is_reduced_to_its_number`
- [x] `test_the_system_version_is_the_one_the_unit_calls_itself`
- [x] `test_version_normalisers_tolerate_absence`

> **New scenario found by a failing test.** `test_ties_round_down_never_up` failed on 55%:
> `0.55 * 50` is `27.499999999999996`, so an input that is mathematically the tie −22.5 dB
> arrives just above it and rounds **up**, one dB louder — the one direction the tie rule
> forbids. `fraction_to_db` now snaps to nine decimal places before rounding.
> Measured across five plausible ranges: one input affected on three of them, none on the other
> two. Rare, but the affected input depends on the range, `vpl`/`vph` are user-configurable,
> and the error is always louder.

> **Scenario moved.** `test_a_codec_mismatch_is_reported_once` belongs to the mirror (T4), not
> here: the codecs are stateless by design, and "report once" is state. Keeping a warn-once
> flag on a module-level codec instance would suppress the warning across all five units after
> the first. `test_a_codec_can_tell_whether_the_wire_shape_matched_its_declaration` covers the
> detection half here; T4 covers the reporting half.

### `mso.py` — mirror and patch applier (T4) — **complete**

37 tests.

*Loading*
- [x] `test_a_fresh_mirror_is_not_loaded`
- [x] `test_the_three_fixtures_load_without_error` (AC-12)
- [x] `test_a_modern_document_populates_the_fields_we_read`
- [x] `test_string_valued_switches_decode_to_booleans` — `/loudness`, `/bassenhance`
- [x] `test_version_strings_are_normalised`
- [x] `test_a_sparse_document_loads_without_error`
- [x] `test_legacy_firmware_has_no_video_fields` — absent disables, never raises
- [x] `test_the_legacy_volume_range_is_read_from_the_unit` — `-60..-5`; anything hardcoding
      `-50..0` fails here

*Change sets*
- [x] `test_the_change_set_is_exactly_the_fields_that_moved`
- [x] `test_a_push_that_changes_nothing_notifies_nobody` (AC-17)
- [x] `test_multiple_moved_fields_all_appear`
- [x] `test_a_single_unwrapped_op_is_accepted`
- [x] `test_status_raw_is_never_walked`
- [x] `test_unknown_paths_are_dropped_silently`
- [x] `test_applying_nothing_is_harmless`

*Container replaces* (AC-13) — one test per subtree rather than one parametrised test, since
each asserts different leaves
- [x] `test_every_container_path_is_declared` — all eight
- [x] `test_a_status_container_replace_rederives_every_leaf`
- [x] `test_a_cal_container_replace_rederives_leaves_and_slots`
- [x] `test_a_videostat_container_replace_rederives_every_leaf`
- [x] `test_a_versions_container_replace_rederives_and_normalises`
- [x] `test_an_upmix_container_replace_rederives_selection_and_visibility`
- [x] `test_a_slots_container_replace_keeps_six_rows`
- [x] `test_an_svronly_container_replace_does_not_raise` — untracked, but it arrives
- [x] `test_absent_keys_are_unspecified_not_cleared`
- [x] `test_a_full_document_is_a_census`

*Dirac slots* (AC-14)
- [x] `test_slots_are_always_six_rows` — parametrised over both firmware shapes
- [x] `test_slot_indices_stay_aligned_with_currentdiracslot`
- [x] `test_a_slot_with_no_name_key_survives_as_an_empty_name`
- [x] `test_a_missing_slot_array_still_yields_six_rows`

*Inputs*
- [x] `test_inputs_are_projected_with_labels_and_visibility`
- [x] `test_an_input_label_push_moves_only_that_input`
- [x] `test_an_input_visibility_push_is_reported`

*Codec mismatch* — moved here from `models.py`, because "report once" is state
- [x] `test_a_codec_mismatch_is_reported_once` (guards HW-02)
- [x] `test_a_matching_codec_reports_no_mismatch`

*The path table*
- [x] `test_every_tracked_path_is_an_absolute_json_pointer`
- [x] `test_field_names_are_unique`

### `options.py` — dropdown construction (T4) — **complete**

20 tests. Not foreseen as a separate module when this document was written: the design listed
these functions under `models.py`, but they consume the mirror's collections, so they landed
with T4.

- [x] `test_only_visible_inputs_are_offered`
- [x] `test_a_blank_label_falls_back_to_a_readable_default`
- [x] `test_duplicate_labels_are_disambiguated_on_every_collision` — every member, not just the
      later one, which would depend on iteration order
- [x] `test_a_label_that_is_unique_is_left_alone`
- [x] `test_the_order_is_canonical_not_dictionary_order` — the same inputs in two orders produce
      identical lists
- [x] `test_the_current_input_is_offered_even_when_invisible`
- [x] `test_the_current_input_is_offered_even_when_absent_from_the_document`
- [x] `test_an_unknown_input_key_still_gets_a_label`
- [x] `test_no_inputs_at_all_is_an_empty_list_not_an_error`
- [x] `test_a_mode_the_unit_hides_is_not_offered`
- [x] `test_a_mode_with_no_visibility_flag_is_shown` — **the rule**, see below
- [x] `test_sound_mode_order_is_canonical`
- [x] `test_the_current_sound_mode_is_offered_even_when_hidden`
- [x] `test_sound_mode_labels_map_back_to_wire_keys`
- [x] `test_every_slot_is_offered_with_its_wire_index`
- [x] `test_duplicate_slot_names_stay_unique_for_free`
- [x] `test_the_current_slot_resolves_by_position_not_by_name` — parametrised
- [x] `test_an_out_of_range_current_slot_reports_nothing_rather_than_the_wrong_one`

> **Spec ambiguity found by a failing test.** Two tests here contradicted each other about
> whether a *missing* `homevis` means hidden or shown. Resolved to **absent means visible**:
> firmware 1.13.x omits the flag entirely, and there is no way to distinguish "this firmware
> does not report visibility" from "this mode is hidden". Defaulting to hidden empties the whole
> dropdown on that firmware; defaulting to visible costs one unwanted entry. The failure is
> asymmetric, so the tolerant default wins.

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
**T6 read path — complete.** 17 tests.

*Listeners*
- [x] `test_a_listener_hears_what_moved`
- [x] `test_a_push_that_changes_nothing_notifies_nobody`
- [x] `test_unsubscribing_stops_the_notifications` — and the mirror still follows the push
- [x] `test_unsubscribing_twice_is_harmless`
- [x] `test_a_listener_that_raises_does_not_take_down_the_connection` — an entity having a bad
      day must not cost the connection for everything else on the unit
- [x] `test_a_document_push_notifies_too`

*Not parse failures*
- [x] `test_an_error_frame_does_not_spend_budget` — `error "bad-verb"`; no re-read, connection
      survives
- [x] `test_an_unknown_shape_does_not_spend_budget` — bare JSON and unknown verbs are free
- [x] `test_a_bare_json_push_is_applied`

*The budget* (AC-09)
- [x] `test_an_undecodable_frame_triggers_one_re_read`
- [x] `test_the_error_path_retry_does_not_reset_the_budget` — **the subtle one**. Demonstrated
      against a deliberately broken implementation: the correct one issues 2 re-reads for 10
      undecodable frames, the broken one issues 10
- [x] `test_the_cap_is_logged_exactly_once` — past the cap the client goes quiet, rather than
      one log line per frame
- [x] `test_a_decodable_message_clears_the_streak` — the cap counts *consecutive* failures
- [x] `test_a_deliberate_refresh_restores_the_budget`
- [x] `test_reconnecting_restores_the_budget`
- [x] `test_the_budget_is_three`
- [x] `test_refreshing_while_disconnected_raises`
- [ ] `test_the_queue_does_not_survive_a_disconnect` (AC-10)
**T5 transport — complete.** 22 tests. Names as shipped:

- [x] `test_connecting_asks_for_the_document_and_loads_it`
- [x] `test_the_url_is_the_controller_endpoint_on_port_eighty`
- [x] `test_the_heartbeat_is_configured_on_the_socket`
- [x] `test_a_refused_connection_raises_rather_than_retrying`
- [x] `test_a_socket_that_never_upgrades_times_out` (AC-01) — the Control4 Critical defect,
      reproduced against a connection that accepts and never upgrades
- [x] `test_the_shipped_connect_timeout_is_fifteen_seconds` — tests use 0.02 s; the default
      must stay the measured one
- [x] `test_a_connection_that_drops_before_the_document_raises`
- [x] `test_start_makes_one_attempt_and_raises` — exactly one `ws_connect` call
- [x] `test_the_reconnect_ladder_only_starts_after_the_first_document`
- [x] `test_stop_is_idempotent`, `test_stop_before_start_is_harmless`
- [x] `test_stopping_closes_the_socket`
- [x] `test_stop_leaves_no_task_running` — a supervisor outliving the entry would keep
      reconnecting to a removed device
- [x] `test_a_dropped_connection_is_re_established_and_re_read` — and `getmso` is re-sent,
      because state after a gap cannot be assumed unchanged
- [x] `test_the_backoff_ladder_climbs_and_caps` — 2/4/8/16/30/60/60/60, each within ±20 %
      (AC-11)
- [x] `test_jitter_actually_varies_the_delay`
- [x] `test_two_clients_do_not_reconnect_in_lockstep` (AC-11)
- [x] `test_the_same_seed_is_reproducible`
- [x] `test_previewing_the_ladder_has_no_side_effect` — added at review: previewing twice gives
      the same answer, and the preview matches what the next real delay turns out to be
- [x] `test_the_ladder_resets_after_a_successful_connection`
- [x] `test_the_module_never_seeds_the_global_random_generator` (AC-11) — **by AST**, not
      substring: the module's own docstring contains the words `random.seed()` as a warning
- [x] `test_the_call_detector_actually_detects` — proves that guard can fail
- [x] `test_the_client_does_not_touch_module_level_random` — exercises the real generator and
      shows global state is unmoved
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

### `scripts/probe_htp1.py` — the read-only probe (T10) — **complete**

9 tests.

- [x] `test_the_probe_exists`
- [x] `test_the_probe_never_mentions_allow_writes` (AC-21) — **stronger than the planned check**.
      The plan said "never passes `allow_writes=True`"; this asserts the script never names the
      keyword at all, so enabling writes cannot be a one-character edit
- [x] `test_the_probe_never_calls_a_write_method`
- [x] `test_the_read_only_detector_actually_detects` — proves both guards above can fail
- [x] `test_the_summary_scrubs_site_data` — unit name, serial, every input label and every
      Dirac slot name checked against the actual digest
- [x] `test_the_summary_answers_the_open_hardware_questions` — HW-02, HW-03, HW-04, HW-07
- [x] `test_the_summary_counts_rather_than_naming` — counts describe the unit; names describe
      the house
- [x] `test_a_legacy_document_reports_the_missing_video_block`
- [x] `test_a_mac_address_is_reported_by_path_not_by_value` — HW-03 asks *whether* a MAC exists;
      the address itself is still site data, so only the path is reported

*Also verified by hand against the fake device over a real socket:* the digest contains no unit
name, serial value, input label or slot name, and `observe` reports zero pushes from an idle
unit — which is the expected result and the reason this integration never polls.

### Package hygiene

- [x] `test_the_client_package_imports_no_home_assistant` — walks `htp1/*.py` and asserts no
      `homeassistant` import. This is the property that keeps the suite runnable on Windows
      (AC-19). Uses an AST walk, not a substring search: the word appears in prose throughout
      this package, so grepping would produce false positives forever
- [x] `test_the_home_assistant_import_detector_actually_detects` — proves the detector above can
      fail, against `import homeassistant`, `from homeassistant.core import ...`, an aliased
      import, and a docstring mention that must *not* trip it. A guard that cannot fail is not
      a guard
- [ ] `test_the_suite_installs_from_requirements_test` — asserts `aiohttp` is declared there
      rather than arriving through `pytest-homeassistant-custom-component`, which is unusable on
      the Windows dev box (Q7)

## Integration Tests (T8, T9) — **complete**

Against `tools/fake_htp1.py`, over a real loopback socket with a real `aiohttp.ClientSession`.
13 tests, 1.4 s for the whole suite including these.

- [x] `test_connect_get_document_and_disconnect` — the happy path end to end
- [x] `test_a_write_comes_back_as_a_push` — the fake broadcasts applied ops, as the real unit
      does to every connected client
- [x] `test_a_front_panel_change_arrives_unrequested` — nothing is asked for; this is why we
      never poll
- [x] `test_junk_input_is_rejected_and_the_connection_survives`
- [x] `test_the_handshake_timeout_fires_against_a_socket_that_never_upgrades` — **the single
      most valuable fault in the set** (AC-01). The only end-to-end proof, and the defect it
      models wedged the Control4 driver permanently
- [x] `test_the_wrong_path_is_refused` — closed with 1008 on anything but `/ws/controller`
- [x] `test_a_document_that_never_decodes_exhausts_the_budget_and_goes_quiet`
- [x] `test_bare_json_payloads_are_understood`
- [x] `test_a_container_replace_from_the_wire_rederives_leaves`
- [x] `test_an_unconfirmed_write_is_rolled_back`
- [x] `test_firmware_without_a_video_block_loses_only_those_fields`
- [x] `test_a_unit_without_a_serial_still_connects`
- [x] `test_a_dropped_connection_is_re_established`

> **Two scenarios dropped, with reasons.** `test_a_trickled_document_reassembles` and
> `test_an_ignored_ping_is_detected_and_reconnects` tested RFC 6455 fragment reassembly and the
> pong deadline. The Control4 driver needed both because it hand-wrote its own codec; here
> aiohttp owns framing and derives the pong deadline from `heartbeat`, so these would test
> aiohttp rather than anything in this repository. `close-after-document` reaches the same
> recovery path, and `test_a_dropped_connection_is_re_established` covers it.

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

## Coverage — measured at the close of M1

```
custom_components/ha_monolith_htp1/htp1/__init__.py     6 stmts    0 miss   100%
custom_components/ha_monolith_htp1/htp1/protocol.py    87 stmts    0 miss   100%
custom_components/ha_monolith_htp1/htp1/options.py     32 stmts    0 miss   100%
custom_components/ha_monolith_htp1/htp1/mso.py        217 stmts    2 miss    99%
custom_components/ha_monolith_htp1/htp1/client.py     319 stmts    8 miss    97%
custom_components/ha_monolith_htp1/htp1/models.py      69 stmts    2 miss    97%
                                              TOTAL  730 stmts   12 miss    98%
```

**The coverage review found real gaps, not just numbers.** `mso.py` started at 88 %, and what was
missing turned out to be device behaviours nothing exercised: `remove` operations, per-slot
`/cal/slots/<n>/name` pushes, and per-mode `/upmix/<mode>/homevis` pushes. `wire_samples.json`
already contained a `remove` sample that no test ever applied to the mirror. Ten tests were added
and it rose to 99 %.

**The twelve remaining statements are justified, not deferred:**

| Where | What | Why it stays uncovered |
|---|---|---|
| `models.py` 121, 124 | `Codec.matches` / `Codec.encode` raising `NotImplementedError` | Abstract base methods. Both concrete codecs override them; reaching these means someone subclassed `Codec` and forgot, which the exception exists to say |
| `client.py` 346–348 | `send_str` raising during a flush | Requires a socket that accepts a write and then fails mid-call. The disconnect path is covered; this is the narrower race, and faking it would test the fake |
| `client.py` 402, 576 | Early returns in `_reconcile` and `_teardown` when there is nothing to do | Guards against double-invocation, reached only by an ordering that no caller produces |
| `client.py` 150, 480, 529 | `host` property; re-raise of an already-typed error; `receive()` raising | Trivial accessor and two re-raise paths |
| `mso.py` 327, 345 | Container replace with a non-dict value; a `/cal` container whose slots are unchanged | Both are reached only when the unit sends a well-formed container that changes nothing |

Chasing these to 100 % would mean writing tests that assert the shape of defensive code rather
than any behaviour a device can produce.

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
