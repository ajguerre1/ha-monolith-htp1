# Backlog

The living list of pending work. **Review it at the start of any work session, and again
before closing one out.**

Rules:

- **IDs are stable and never reused.** A closed item keeps its ID forever.
- Status: `open` · `in-progress` · `blocked` · `parked` · `done`
- Priority: `H` · `M` · `L`
- **An item closes only with evidence** — a test name, a CI run number, or a live observation.
  "It looks right" is not evidence.

Task tracing via the ai-devkit `task` CLI is unavailable in v0.50.1 (`unknown command 'task'`),
so this file is the record.

---

## Open

### Hardware questions — must be settled before v1.0 (M4)

These need real units. All are read-only except where marked; writes go to the **designated lab
unit only** (named in the gitignored `local/lab-unit.md`), after asking.

| ID | Pri | Item | Method | Why it blocks |
|----|-----|------|--------|---------------|
| `HW-01` | H | Does the unit keep its network stack alive when `powerIsOn` is false? | **Write** `/powerAction: "off"`, watch the socket 120 s | Decides whether `TURN_ON` is reachable at all, and therefore whether `MediaPlayerEntityFeature.TURN_ON` may be declared. Both units report `fastStart: "on"`, which suggests yes. Record as `POWER_OFF_KEEPS_NETWORK` in `const.py`, referenced in exactly one place. |
| `HW-05` | M | Does `/status` keep reporting a stale format while the unit is powered off? | Read-only, after `HW-01` | If it does, a dashboard shows "Dolby Atmos" on a dark processor. Gate those sensors to `None` via `BLANK_STATUS_WHEN_OFF`. |
| `HW-06` | M | Does lip sync require the dual write (`/cal/lipsync` **and** `/inputs/<current>/delay`)? | **Write** | The vendor's own client writes both. Writing only the first is believed to leave the unit's own display disagreeing. |
| `HW-08` | L | Does a front-panel change propagate as an unrequested push? | Read-only `observe`, with someone at a unit | Not settled by the T11 run: nobody was at a panel, so 45 s of idle observation proved the *absence* of chatter but not the presence of propagation. The Control4 project observed it, so this is confirmation rather than discovery. |

### Build

| ID | Pri | Item | Notes |
|----|-----|------|-------|
| `M1-01` | H | Vendored client: `protocol.py`, `models.py`, `mso.py`, `client.py` | Feature `htp1-client`. Test-first. No Home Assistant imports. |
| `M1-02` | H | Port MSO fixtures `modern` / `legacy` / `sparse` from the Control4 driver's `tests/fixtures.lua` to JSON | Already sanitised there; re-check before committing. |
| `M1-03` | H | Port `tools/fake-htp1.py`, adding the `accept-tcp-no-upgrade` fault | That fault is the only way to prove the 15 s handshake timeout fires. |
| `M2-01` | H | Integration core: coordinator, entity base, config flow, diagnostics, strings | Feature `integration-core`. |
| `M3-01` | H | Five entity platforms, description-table driven | Feature `entity-platforms`. |
| `M4-01` | H | Live validation and cutover from `monoprice_htp1` | Feature `live-cutover`. Old integration's files stay on disk as rollback. |
| `M5-01` | M | Author `.claude/skills/monolith-htp1/SKILL.md` | Shape it like the `somfy-sdn` skill: traps, and a "common mistake → consequence" table. No skill for HACS or HA custom-component development exists anywhere — verified across 74 registries. |
| `M5-02` | M | PR the brand icons to `home-assistant/brands` | Required for HACS default-list inclusion. The assets themselves now exist in-repo (`M0-02`), which is enough for the HACS action but **not** for the default list — that check requires the brands repository. Replace the placeholder artwork with something better first if anyone wants to. |
| `M5-03` | L | Submit to the HACS default list | Needs: passing HACS action with no ignores, passing hassfest, a release created *after* both pass, plus repo description and topics. |

---

## Completed

| ID | Item | Evidence |
|----|------|----------|
| `HW-02` | `/eq/tc` measured: **`bool`** on all five units | `probe_htp1.py summary`, 2026-08-16, firmware V2.1.2 ×5. `two_state_paths` reports `/eq/tc: bool`, `/loudness: string`, `/bassenhance: string`, `/muted: bool`, `/powerIsOn: bool` — the declared codecs are correct. **Only 2.1.2 was measured**; no unit here runs 1.13.x, so that family stays inferred and the warn-once mismatch check stays. |
| `HW-03` | **No MAC address anywhere in the document** | `probe_htp1.py` plus a loose scan for MAC-shaped values and `*mac*` keys: the only matches are `/inputs/*/macro`. `/network/eth0` carries `dhcp`, `addr`, `mask`, `gw` and nothing else, and `addr`/`mask`/`gw` are empty strings. **Consequence: DHCP self-heal is not buildable from the document.** The README must recommend a reservation and must not imply a self-heal; `"dhcp": [{"registered_devices": true}]` needs a MAC to register as a device connection. |
| `HW-04` | Volume range measured: **`vpl = -50`, `vph = 0` on all five** | `probe_htp1.py summary` ×5, 2026-08-16. Matches the value the design assumed, now confirmed rather than assumed. Still read live — they remain user-configurable. |
| `HW-07` | `/status` vocabulary captured from all five | Observed: `SurroundMode` ∈ {`Native Dolby ATMOS`, `Dolby Surround`}, `DECSourceProgram` ∈ {`Dolby MAT/PCM`, `PCM`}, `DECProgramFormat` ∈ {`Object Audio`, `2.0.0`}, `ENCListeningFormat` ∈ {`3.1.2`, `5.1.2`, `5.2.2t`, `7.2.2`}, sample rates `48 kHz`, `DiracState` `off`. Free-text sensors, as designed — `5.2.2t` is exactly why they are not enumerated. |
| `M0-01` | AI DevKit initialized, all 7 phases, 20 built-in skills | `npx ai-devkit@latest lint` → "All checks passed"; `skill list` → 20 skills incl. every `dev-*` phase skill |
| `M0-02` | Brand icons generated so the HACS `brands` check passes from this repo | `scripts/make_brand_icons.py` → `brand/icon.png` 256×256 RGBA, `icon@2x.png` 512×512 RGBA. CI run 31918079021 failed `brands` (8/9); run **31918223147** on commit `7acaf56` → "All (9) checks passed". |
| `M0-03` | Repository published and CI green end to end | `ajguerre1/ha-monolith-htp1`, public, description + 8 topics. CI run **31918223147**: hassfest ✓, HACS ✓, ruff ✓, pytest ✓ (6 tests), strings parity ✓. |
