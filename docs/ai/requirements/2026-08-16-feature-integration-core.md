---
phase: requirements
title: Requirements & Problem Understanding
description: Clarify the problem space, gather requirements, and define success criteria
---

# Requirements & Problem Understanding — `integration-core`

Milestone M2: the Home Assistant layer that turns the vendored client into a config entry —
setup, coordinator, entity base, config flow, diagnostics, translations. No entity platforms;
those are M3.

## Problem Statement

M1 produced a client that connects, mirrors state, coalesces writes and reconnects safely. It
imports no Home Assistant and therefore does nothing inside Home Assistant. M2 is the adapter.

The integration it replaces, `ross/ha-monoprice-htp1`, is instructive about what to get right,
because its gaps are visible in the live system today:

- **No device registry entries.** `device_attr(entity, 'name')` returns `None` for all five, so
  there are entities but no devices — no area-by-device, no `via_device`, no diagnostics.
- **No friendly names.** `state_attr(e, 'friendly_name')` is `None` on all five.
- **`unique_id` is the host**, so a DHCP move orphans the entry.
- **No `ConfigEntryNotReady`**, so a unit that is off at Home Assistant startup fails setup hard
  rather than retrying.

## Goals & Objectives

**Primary**

1. A config entry per unit that survives restarts, reloads cleanly, and never leaks a session.
2. One device per processor, correctly identified, so entities inherit an area.
3. Push-driven state with **no polling**, and no state written unless something changed.
4. Failures that are honest: unavailable when we cannot talk to the unit, unknown when we can
   but it has not said.

**Secondary**

5. Diagnostics that are safe to paste into a public issue.
6. Options that change behaviour, not options that duplicate the entity registry.

**Non-goals**

- Entity platforms — M3.
- Discovery. HW-03 measured no MAC in the document, so DHCP tracking is not buildable; the
  README says so and recommends a reservation.
- Reauthentication. The unit has no authentication at all.
- YAML configuration. Config entry only.

## User Stories & Use Cases

- As **a user**, I add the integration, type an address, and get a named device in the right
  area, so my dashboard groups it sensibly.
- As **a user**, when a processor is unplugged, its entities go unavailable rather than
  reporting stale values, and come back on their own when it returns.
- As **a user**, I can change a unit's address without deleting and re-adding it.
- As **a user filing a bug**, I can attach diagnostics without publishing my room layout.
- As **the M3 platforms**, I want one coordinator to subscribe to and one place that knows how
  to translate a Home Assistant value into a device write.

**Edge cases**

- A unit that is off, or still booting, when Home Assistant starts.
- Two config entries pointed at the same unit.
- An entry whose unit has been replaced by a different one at the same address.
- A unit with no serial number.
- Home Assistant shutting down while a socket is wedged.

## Success Criteria

| # | Acceptance criterion | Test |
|---|---|---|
| AC-30 | Setup succeeds against a reachable unit and forwards to platforms | `test_setup_creates_the_entry_and_device` |
| AC-31 | Setup raises `ConfigEntryNotReady` when the unit is unreachable, so HA retries | `test_an_unreachable_unit_defers_setup` |
| AC-32 | Setup never leaks a client session when a later step fails | `test_a_failed_setup_closes_the_client` |
| AC-33 | Unload stops the client and removes the entry's runtime data | `test_unload_stops_the_client` |
| AC-34 | The entry stores its runtime in `entry.runtime_data`, not `hass.data` | `test_runtime_data_is_used` |
| AC-35 | One device per entry, with manufacturer, model, serial, sw version and a link to the unit's own web UI | `test_the_device_is_registered_with_identity` |
| AC-36 | The coordinator polls **never** — `update_interval` is None | `test_the_coordinator_does_not_poll` |
| AC-37 | A push updates entities without any request being sent | `test_a_push_updates_the_coordinator` |
| AC-38 | Entities are unavailable while the client is disconnected, and recover | `test_entities_go_unavailable_and_recover` |
| AC-39 | An outage logs once, and recovery logs once — not once per retry | `test_an_outage_logs_once_and_recovery_logs_once` |
| AC-40 | The config flow accepts a host, validates by reading a document, and uses the serial as unique id | `test_the_config_flow_creates_an_entry` |
| AC-41 | The flow reports distinct errors for unreachable, timeout, and not-an-HTP-1 | `test_the_config_flow_reports_why_it_failed` |
| AC-42 | A second entry for the same serial is refused | `test_a_duplicate_unit_is_refused` |
| AC-43 | A unit with no serial still configures, keyed on host | `test_a_unit_without_a_serial_falls_back_to_the_host` |
| AC-44 | Reconfigure updates the host, and refuses a different unit | `test_reconfigure_updates_the_host`, `test_reconfigure_refuses_a_different_unit` |
| AC-45 | Diagnostics contain no host, serial, unit name, input label or Dirac slot name | `test_diagnostics_leak_no_site_data` |
| AC-46 | `strings.json` and `translations/en.json` are byte-identical | `test_strings_and_translations_match` |
| AC-47 | Every error and abort key the flow can emit exists in `strings.json` | `test_every_flow_message_has_a_translation` |
| AC-48 | Options change behaviour without reloading the entry | `test_changing_options_does_not_reload_the_entry` |

## Constraints & Assumptions

**The binding constraint: Home Assistant cannot be imported on the development machine.**
`homeassistant.runner` imports POSIX-only `fcntl`. Every test in this milestone therefore lives
in `tests/ha/` and runs **only in CI**. Locally the gate is `ruff` plus the M1 offline suite;
CI is the authority. The M1 socket failure was the same lesson delivered gently — here it is
structural, so the loop is write, push, read CI.

**Home Assistant version.** Target 2026.8.2, which is what the live system runs. Use
`entry.runtime_data` with a typed `ConfigEntry` alias and `AddConfigEntryEntitiesCallback`;
both are current, and `hass.data[DOMAIN][entry.entry_id]` is the pattern they replaced.

**Measured facts that constrain the design** (from T11, five units, firmware 2.1.2):

- No MAC anywhere in the document → no DHCP discovery, and the README must not imply one.
- `vpl`/`vph` are −50/0 today but remain user-configurable; read them live.
- `/eq/tc` is a boolean, `/loudness` and `/bassenhance` are strings.
- All five units report a serial, so the no-serial path is a fallback rather than the norm.

**House constraint.** ~50 wall panels receive every state change. Writing state that did not
change is a regression, not a detail.

## Questions & Open Items

**Open, and answered by assumption for now:**

- **HW-01** — whether the unit's network stack survives `powerIsOn: false` — is still open and
  needs a write to the lab unit. M2 records the answer as a single constant
  `POWER_OFF_KEEPS_NETWORK`, referenced in exactly one place, and ships assuming **yes**. Being
  wrong that way means a `TURN_ON` write simply never lands, which is the safe direction.
- **HW-05** and **HW-06** likewise wait for M4.

**Resolved by measurement:** HW-02, HW-03, HW-04, HW-07 — see the backlog.

**No blocking questions.** M2 can proceed.
