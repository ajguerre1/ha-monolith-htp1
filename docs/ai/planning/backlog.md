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
| `HW-02` | H | Is `/eq/tc` a bool, or the strings `"off"`/`"on"`, on **both** firmwares? | Read-only `getmso` | Its two neighbours `/loudness` and `/bassenhance` are strings. This asymmetry is exactly the kind of thing that differs across firmware, and getting it wrong makes the tone-control switch silently inoperative. |
| `HW-03` | M | Does the MSO document carry a MAC address anywhere (`/network`, `/nic`, `/eth`)? | Read-only `getmso` | If yes, `"dhcp": [{"registered_devices": true}]` plus `CONNECTION_NETWORK_MAC` makes DHCP self-heal real. If no, the README must recommend a reservation and must **not** imply a self-heal that cannot fire — `_abort_if_unique_id_configured(updates=...)` never triggers without a discovery source. |
| `HW-04` | H | Real `/cal/vpl` and `/cal/vph` on all five units | Read-only | The entire volume mapping derives from them and they are user-configurable. Never hardcode −50..0. |
| `HW-05` | M | Does `/status` keep reporting a stale format while the unit is powered off? | Read-only, after `HW-01` | If it does, a dashboard shows "Dolby Atmos" on a dark processor. Gate those sensors to `None` via `BLANK_STATUS_WHEN_OFF`. |
| `HW-06` | M | Does lip sync require the dual write (`/cal/lipsync` **and** `/inputs/<current>/delay`)? | **Write** | The vendor's own client writes both. Writing only the first is believed to leave the unit's own display disagreeing. |
| `HW-07` | L | Actual `/status` string vocabulary across the five units | Read-only | Low risk by design — these are free-text sensors — but worth capturing so the README's example values are real rather than invented. |

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
| `M0-01` | AI DevKit initialized, all 7 phases, 20 built-in skills | `npx ai-devkit@latest lint` → "All checks passed"; `skill list` → 20 skills incl. every `dev-*` phase skill |
| `M0-02` | Brand icons generated so the HACS `brands` check passes from this repo | `scripts/make_brand_icons.py` → `brand/icon.png` 256×256 RGBA, `icon@2x.png` 512×512 RGBA. CI run 31918079021 failed `brands` (8/9); run **31918223147** on commit `7acaf56` → "All (9) checks passed". |
| `M0-03` | Repository published and CI green end to end | `ajguerre1/ha-monolith-htp1`, public, description + 8 topics. CI run **31918223147**: hassfest ✓, HACS ✓, ruff ✓, pytest ✓ (6 tests), strings parity ✓. |
