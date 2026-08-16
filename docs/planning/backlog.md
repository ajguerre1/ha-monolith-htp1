# Backlog

The living list of pending work. **Review it at the start of any work session, and again
before closing one out.**

Rules:

- **IDs are stable and never reused.** A closed item keeps its ID forever.
- Status: `open` · `in-progress` · `blocked` · `parked` · `done`
- Priority: `H` · `M` · `L`
- **An item closes only with evidence** — a test name, a CI run number, or a live observation.
  "It looks right" is not evidence.

There is no separate issue tracker for this project. This file is the record.

---

## Open

### Hardware questions — must be settled before v1.0 (M4)

These need real units. All are read-only except where marked; writes go to the **designated lab
unit only** (named in the gitignored `local/lab-unit.md`), after asking.

| ID | Pri | Item | Method | Why it blocks |
|----|-----|------|--------|---------------|
| `HW-08` | L | Does a front-panel change propagate as an unrequested push? | Read-only `observe`, with someone at a unit | Not settled by the T11 run: nobody was at a panel, so 45 s of idle observation proved the *absence* of chatter but not the presence of propagation. An earlier driver observed it, so this is confirmation rather than discovery. |

### Build

| ID | Pri | Item | Notes |
|----|-----|------|-------|
| `M5-03` | L | Submit to the HACS default list | **Prepared, awaiting owner submission.** Branch `add-ha-monolith-htp1` is pushed to the owner's `hacs/default` fork: a one-line insert, valid JSON, and the repo's own `scripts/is_sorted.py` passes. Not opened by tooling, because the pull request template is a set of first-person attestations ("I've read the publishing documentation") that only the owner can truthfully make. Links it asks for are in `local/hacs-submission.md`. |
| `M5-04` | L | Replace the placeholder README screenshot section | Not blocking. Nothing shows what the integration looks like in use. |

---

## Completed

| ID | Item | Evidence |
|----|------|----------|
| `HW-01` | **Shutdown ends communication; sleep does not.** The question was framed as one state and is really two | Measured 2026-08-16 on the lab unit: `/powerAction: "off"` — no answer on port 80 within 10 s, still silent after 4 minutes, needed the front-panel button. A control unit answered throughout, so the network path was fine. **The framing was the error**: `off` is the web UI's SHUTDOWN, while SLEEP is the standby that keeps networking. `turn_off` now maps to `sleep`, and shutdown is its own opt-in button. |
| `M4-01` | **Cut over. Five units live on `ha_monolith_htp1`, `monoprice_htp1` removed** | 2026-08-16. Installed **through HACS** as a custom repository from release `v0.1.0` — `installed: true`, `installed_version: v0.1.0`, files under `/config/custom_components/ha_monolith_htp1/`, which proves requirement 4 end to end rather than asserting it. Five old entries removed, one restart (116 s), five entries added via the config flow, each titled from the unit's own name. **100 registry entities = 20 per unit, 70 enabled = 14 per unit**, matching `EXPECTED_ENTITIES` and `DISABLED_BY_DEFAULT` exactly. All five shutdown buttons `disabled_by=integration`. `supported_features=69004` = the seven intended flags including `TURN_ON`. Volume verified against the device: −43 dB over [−50, 0] reads 0.14. Devices placed in their five areas, so all 14 entities inherit an area — the thing the old integration could not do, having created no device at all. `media_player.htp1_<room>` ids reclaimed. **Log: one line, the standard "custom integration not tested" boilerplate. Zero errors from our code.** Diagnostics checked against a real unit, not a fixture: 5,888 bytes, no host, serial, unit name or input label. |
| `M2-01` | Integration core: coordinator, entity base, config flow, diagnostics, strings | Feature `integration-core`. `tests/ha/test_init.py`, `test_config_flow.py`, `test_diagnostics.py`. Verified live in `M4-01`: `entry.runtime_data` in use, options change without reloading the entry, diagnostics redacted against a real unit. |
| `M3-01` | Entity platforms, description-table driven | Feature `entity-platforms`. **Six platforms, not the five originally scoped** — `button` was added for shutdown once the power model was corrected. `test_the_entity_inventory_is_exactly_this` pins the ids; `M4-01` confirmed 14 enabled and 6 gated per unit across five live units. |
| `M5-02` | **Obsolete, and already satisfied.** No brands pull request is needed | `home-assistant/brands` stopped accepting pull requests for custom components; its PR template says so outright and points at the Brands Proxy API (HA 2026.3). Custom integrations now serve their own images from a `brand/` directory inside the integration, which this repo has shipped since `M0-02`. Verified live rather than assumed: `GET /api/brands/integration/ha_monolith_htp1/icon.png` returns HTTP 200 with a body whose SHA-256 matches the committed file byte for byte. **The task was built on a requirement that no longer exists.** |
| `M5-07` | Real brand artwork, and the display name corrected | Owner-supplied logo; only the mark is used, since the wordmark is illegible at the ~48 px the integrations list renders. `scripts/make_brand_icons.py` derives both sizes by scanning rows for bands of artwork and splitting at the widest gap, rather than hardcoded crops that would silently produce nonsense against a different source. Name is now `Monolith HTP-1` everywhere; the old one was the repository name leaking into the product name and already disagreed with the config flow. Released as `v0.1.1`, updated through HACS on the live system, restart verified: 5 entries loaded, 100 registry entities, 70 enabled, 5 devices with areas, no errors. |
| `M5-01` | **Device notes written** | `docs/htp1-device-notes.md`: transport, the trap that costs a physical trip, volume rules, absence and asymmetry, a 20-row "common mistake → consequence" table, and the Home Assistant specifics this device forces. Privacy-checked: no addresses, unit names or input labels. |
| `M5-06` | Durable findings stored in the machine knowledge store | `project:ha-monolith-htp1`: the power model (sleep vs shutdown, and the two traps that produced the original error) and the lip-sync dual write. `global`: reaching Home Assistant from a DNS-blocked sandbox with a pinned resolver rather than by disabling TLS verification. |
| `M5-05` | **`v0.1.0` tagged and released** | GitHub release `v0.1.0`, CI green on `dcf4b24`. README rewritten for a version people can install. |
| `HW-06` | **The dual write is required.** The unit does not propagate `/cal/lipsync` to the current input's delay | Measured 2026-08-16 on the lab unit: writing `/cal/lipsync` alone moved it 0 → 120 while all 21 inputs stayed at `delay: 0`. Implemented as `Htp1Coordinator.async_set_lip_sync`, one `async_write_many` so the client coalesces both into a single `changemso`. `test_lip_sync_writes_both_paths_at_once`, `test_lip_sync_without_a_known_input_writes_the_setting_alone`. **The measuring script crashed mid-run** on a Windows console encoding error (`→` under cp1252) after the write and before its restore, leaving the unit at 120. Recovered by reading the other four units — all four read `lipsync: 0` with all delays 0 — then writing 0 back and confirming against a fresh document. Restore now runs in a `finally`. |
| `HW-01b` | **Sleep keeps the network, and `/status` goes stale there** | Measured 2026-08-16 on the lab unit. Reachability: 9/9 **fresh** sockets opened during 90 s of sleep returned a full document — fresh, not the held one, because a half-open socket looks alive from this side for minutes and the question is whether Home Assistant could reach a unit it is *not* already talking to. `/powerIsOn` went False, `/volume` `/input` `/muted` survived untouched, and `/powerIsOn: true` woke it remotely. **`SLEEP_KEEPS_NETWORK = True` and `TURN_ON` are now measured rather than assumed.** Staleness: asleep, `/status` still read `Dolby Surround` / `5.1.2` / `PCM` and pushed `listening_format` **twice** in a 20 s window — closed by `HW-09`. |
| `HW-09` | Status sensors blanked when the unit is off, and dash placeholders read as no reading | Found while measuring `HW-01b`. A sleeping processor announced a soundtrack on every wall panel, and `/videostat` fills unread fields with `--` / `---` / `-----`. `test_a_sleeping_unit_reports_no_signal`, `test_waking_restores_the_readings`, `test_a_field_of_dashes_is_not_a_reading`, `test_a_real_value_containing_a_dash_survives`, `test_a_sleeping_unit_that_keeps_talking_moves_no_panel`. |
| `HW-05` | Moot: `/status` cannot be read while the unit is shut down | It stops answering entirely, so there is nothing to read. For sleep the question would reappear, and `HW-01b` covers it. |
| `HW-02` | `/eq/tc` measured: **`bool`** on all five units | `probe_htp1.py summary`, 2026-08-16, firmware V2.1.2 ×5. `two_state_paths` reports `/eq/tc: bool`, `/loudness: string`, `/bassenhance: string`, `/muted: bool`, `/powerIsOn: bool` — the declared codecs are correct. **Only 2.1.2 was measured**; no unit here runs 1.13.x, so that family stays inferred and the warn-once mismatch check stays. |
| `HW-03` | **No MAC address anywhere in the document** | `probe_htp1.py` plus a loose scan for MAC-shaped values and `*mac*` keys: the only matches are `/inputs/*/macro`. `/network/eth0` carries `dhcp`, `addr`, `mask`, `gw` and nothing else, and `addr`/`mask`/`gw` are empty strings. **Consequence: DHCP self-heal is not buildable from the document.** The README must recommend a reservation and must not imply a self-heal; `"dhcp": [{"registered_devices": true}]` needs a MAC to register as a device connection. |
| `HW-04` | Volume range measured: **`vpl = -50`, `vph = 0` on all five** | `probe_htp1.py summary` ×5, 2026-08-16. Matches the value the design assumed, now confirmed rather than assumed. Still read live — they remain user-configurable. |
| `HW-07` | `/status` vocabulary captured from all five | Observed: `SurroundMode` ∈ {`Native Dolby ATMOS`, `Dolby Surround`}, `DECSourceProgram` ∈ {`Dolby MAT/PCM`, `PCM`}, `DECProgramFormat` ∈ {`Object Audio`, `2.0.0`}, `ENCListeningFormat` ∈ {`3.1.2`, `5.1.2`, `5.2.2t`, `7.2.2`}, sample rates `48 kHz`, `DiracState` `off`. Free-text sensors, as designed — `5.2.2t` is exactly why they are not enumerated. |
| `M1-01` | Vendored client: `protocol.py`, `models.py`, `mso.py`, `options.py`, `client.py` | 280 tests, 98 % coverage of `htp1/`, no Home Assistant import (`test_the_client_package_imports_no_home_assistant`) |
| `M1-02` | MSO fixtures written from scratch, not ported | `tests/fixtures/{mso_modern,mso_legacy,mso_sparse,wire_samples}.json`; `test_fixtures_carry_no_site_data` |
| `M1-03` | Fake device with fault injection, incl. `accept-tcp-no-upgrade` | `tools/fake_htp1.py`; `test_the_handshake_timeout_fires_against_a_socket_that_never_upgrades` proves AC-01 over a real socket |
| `M1-04` | Read-only probe, run against all five units | `scripts/probe_htp1.py`; HW-02/03/04/07 closed 2026-08-16 |
| `M1-05` | Acceptance-criteria traceability enforced | `tests/test_traceability.py`. The audit that motivated it found 9 of 21 criteria naming tests that no longer existed |
| `M0-01` | Documentation structure initialised across all seven phases | `docs/{requirements,design,planning,implementation,testing,deployment,monitoring}/`, each with a README; lint clean |
| `M0-02` | Brand icons generated so the HACS `brands` check passes from this repo | `scripts/make_brand_icons.py` → `brand/icon.png` 256×256 RGBA, `icon@2x.png` 512×512 RGBA. CI run 31918079021 failed `brands` (8/9); run **31918223147** on commit `7acaf56` → "All (9) checks passed". |
| `M0-03` | Repository published and CI green end to end | `ajguerre1/ha-monolith-htp1`, public, description + 8 topics. CI run **31918223147**: hassfest ✓, HACS ✓, ruff ✓, pytest ✓ (6 tests), strings parity ✓. |
