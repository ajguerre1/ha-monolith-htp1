# HA Monolith HTP1 — working notes

A Home Assistant custom integration for the Monoprice Monolith HTP-1 AV processor, installable
through HACS. Domain `ha_monolith_htp1`, package `custom_components/ha_monolith_htp1/`.

## Hard constraints

- **Five of these processors are live in an occupied home.** A stray volume, power or input
  command is immediately audible in someone's room. Only **one designated lab unit may
  receive writes**, and only after asking. Which unit that is, and its address, live in the
  gitignored `local/lab-unit.md` — never in this file, because this repo is public. Every
  other unit is **read-only**: connect, send `getmso`, observe `msoupdate`, disconnect.
  Reading is provably passive; the unit serves concurrent controller connections
  independently and will not fight the web UI.
- **Ask before each new class of write** (volume, power, input, Dirac slot, lip sync), one
  path per run, recording before/after from a `getmso`. Never send `/powerAction: "reboot"`
  outside a deliberate, agreed reboot test.
- **This repo is public — no real data, ever.** No real IP addresses, hostnames, serial
  numbers, unit names, input labels, Dirac slot names, room names or occupant names in any
  file, commit message, doc or issue. Committed docs use labelled placeholders
  (`192.168.1.50` — *a placeholder, not a real address*); tests use `10.0.0.1` / `127.0.0.1`.
  Real values live in the gitignored `local/` directory; raw captures in `scripts/output/`.
  **A real `mso` document is site data** — it carries the owner's input labels and unit name,
  so scrub it before it becomes a fixture.
- **Home Assistant credentials never enter this repo.** They come from the machine-global
  store `~/.ha/.env` (`. ~/.ha/load.sh`, then `$HA_URL` / `$HA_TOKEN` / `ssh ha`). Never copy
  them into a project file, never print a token, never pass one as a command-line argument.
  The HTP-1 itself has no credentials — no auth, no TLS. What needs protecting here is the
  topology: which rooms exist and what is plugged into each input.
- **Panel fan-out.** The live Home Assistant drives ~50 wall panels that receive every state
  change. Write entity state only when something actually changed. A chatty integration is a
  regression, not a detail.
- **No external runtime dependencies.** `manifest.json` keeps `requirements: []`; the client
  is vendored under `custom_components/ha_monolith_htp1/htp1/`. Never a `git+https`
  requirement — Home Assistant's `is_installed()` returns False for URL requirements, so it
  would be refetched on every restart.

## The device, in one paragraph

`ws://<host>/ws/controller`, port 80, no auth, no TLS, no REST API, no mDNS/SSDP. Text frames
of `verb[space]JSON`, **split on the first space only**. `getmso` → `mso {…}` (~38 KB).
`changemso [ops]` writes RFC 6902 `replace` operations. The unit pushes `msoupdate [ops]` on
every change from any source including the front panel — sometimes as a single unwrapped op,
and on newer firmware sometimes as bare JSON with no verb. Junk input returns
`error "bad-verb"` and **the connection survives**. Verified live on firmware 1.13.3 and
2.1.1. Full reference in `docs/ai/design/`.

## Invariants that came from real defects

Each of these was earned in the Control4 Monolith HTP-1 driver. Do not "simplify" one away.

1. **15 s connect/handshake timeout.** The unit accepts TCP on :80 before `/ws/controller` is
   live after a reboot; without the timeout the client wedges forever.
2. **"Already there" guard before every write.** Without it a held volume ramp rewrote the
   same dB ~600 times over a ten-second hold.
3. **Round half DOWN** (`ceil(x - 0.5)`), never `round()` — Python's is banker's rounding.
   Over a −50..0 dB range every odd percentage lands exactly on a half-dB, so the tie rule
   decides about half of all inputs, and volume must land quieter than asked, never louder.
4. **Write queue: 50 ms debounce, coalesced by path**, flushed as one `changemso`. Never send
   an empty op array. `replace` only.
5. **Parse-failure budget of 3**, reset *only* on deliberate re-requests — never in the error
   path's own retry, or you rebuild an unthrottled `getmso` storm against a live unit.
6. **Discard the write queue on disconnect.** Replaying it applies a stale command minutes
   later.
7. **Per-client `random.Random(seed)` for backoff jitter** — never `random.seed()`, which
   mutates global state for all of Home Assistant. Unseeded RNG made two instances reconnect
   in lockstep.
8. **Absence tolerance everywhere.** A missing path disables the feature that needs it rather
   than erroring.

## Development lifecycle — AI DevKit

All work follows the **AI DevKit** lifecycle (v0.50.1). Use `dev-lifecycle` to pick the phase.
Phase docs live under `docs/ai/<phase>/`; create them with
`npx ai-devkit@latest docs init-feature <name>` and use the returned paths as authoritative.

| Phase | Skill |
|-------|-------|
| Setup / resume workspace | `dev-worktree` |
| 1–2 Requirements | `dev-requirements` |
| 3 Design | `dev-design` |
| 4, 6 Planning | `dev-planning` |
| 5, 7 Implementation | `dev-implementation` |
| 8 Testing | `dev-testing` |
| 9 Review | `dev-review` |

**Propose the phase and wait for approval before executing it.** Supporting skills: `tdd` for
every implementation task, `verify` before any completion claim, `memory` before non-trivial
work, `structured-debug` for protocol and transport faults.

**Task tracing is unavailable** — ai-devkit 0.50.1 ships the `task` skill but no `task` CLI
command (`npx ai-devkit@latest task list --json` → `unknown command 'task'`). Progress is
tracked in `docs/ai/planning/backlog.md` instead: stable IDs, never reused, and an item closes
only with real evidence (a test name, a CI run number, or a live observation).

The 20 built-in AI DevKit skills are gitignored rather than vendored, because this repo is
public. Restore them in a fresh clone with
`npx ai-devkit@latest init -a -e claude --built-in --yes`.

## Testing

- **Offline:** `pytest tests/ -v`. No Home Assistant import, runs on Windows.
- **HA-dependent:** `tests/ha/` needs `pytest-homeassistant-custom-component`, which pulls in
  Home Assistant — **not importable on Windows** (`homeassistant.runner` imports POSIX-only
  `fcntl`). Those run in CI only.
- **Lint:** `ruff check .` **and** `ruff format --check .` — CI runs both and stops at the
  first failure, so a green `check` can still hide a `format` failure. Upgrade ruff before
  trusting a local run; CI always installs the latest.
- **Fake device:** `tools/fake-htp1.py` speaks the real protocol with fault injection. The
  fault that matters most is `accept-tcp-no-upgrade` — it is the only way to prove the 15 s
  handshake timeout actually fires.

## Memory

Before non-trivial work:
`npx ai-devkit@latest memory search -q "<topic>" --scope project:ha-monolith-htp1`.
Related prior knowledge lives at `--scope project:control4-ha` (the Control4 driver for this
same processor). Store durable findings with `/remember` or `memory store`.

> On Windows, run `memory store` from the **Bash** tool, not PowerShell — PowerShell mangles
> long `--content` arguments and produces a misleading "must be at least 50 characters" error.

## Git sync

Public remote `origin` → `ajguerre1/ha-monolith-htp1`. **After every local commit, push to
`origin/main`.** Pause and confirm before pushing only when the push carries specific risk:
site data in the diff, a force-push, or rewriting already-pushed history. This is a manual
step, not a hook — an unconditional auto-push cannot make that judgment.

Releases are tagged semver; HACS offers updates from GitHub releases.
