# HA Monolith HTP1

A Home Assistant integration for the **Monoprice Monolith HTP-1** 16-channel AV processor,
installable and updatable through [HACS](https://hacs.xyz).

> **Status: in development.** The scaffold and CI are in place; the client and entities are
> being built. Not yet ready to install.

## Why this exists

The HTP-1 speaks a WebSocket protocol that pushes every state change — including changes made
on the front panel or in the vendor's own web UI — to every connected client. That makes it a
natural fit for a push-based Home Assistant integration with no polling at all.

Design principles:

- **Push, never poll.** An idle connection to the unit was measured sending *zero* bytes over
  90 seconds after the initial state read. Any poll interval would be pure waste.
- **The device's own values are the truth.** Volume is integer dB clamped to the unit's
  user-configurable range; the Home Assistant 0–1 level is derived from the dB the unit
  *confirms*, never from what was requested.
- **Quiet on the bus and quiet in the log.** State is written only when something actually
  changed, and a unit that is switched off overnight produces a handful of log lines rather
  than hundreds.
- **No runtime dependencies.** The protocol client is vendored, so `manifest.json` keeps
  `requirements: []`.

## Hardware

Verified against Monolith HTP-1 firmware **1.13.3** and **2.1.1**. The two firmware families
report different documents — 2.1.x adds `channeltrim`, `dialnorm` and `shaker`; 1.13.x has no
video status block at all — so every read is absence-tolerant and features whose data the unit
does not report are simply not created.

The unit exposes **no authentication and no TLS**, and no REST API. Treat network access to it
as equivalent to control of it.

## Installation

Once released:

1. In HACS, add `https://github.com/ajguerre1/ha-monolith-htp1` as a custom repository of
   category **Integration**.
2. Install **HA Monolith HTP1** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → HA Monolith HTP1**, then enter the
   processor's address. Repeat once per unit.

There is no discovery: the HTP-1 advertises no mDNS or SSDP service. Give each unit a DHCP
reservation or a static address.

## Development

```bash
pip install -r requirements-test.txt
pytest tests/ -v          # client and packaging tests; no Home Assistant needed
ruff check . && ruff format --check .
```

Tests are split deliberately. `tests/` imports no Home Assistant and runs anywhere, including
Windows. `tests/ha/` needs `pytest-homeassistant-custom-component` and therefore Linux, so it
runs in CI.

This project follows the [AI DevKit](https://github.com/codeaholicguy/ai-devkit) lifecycle;
phase documentation lives under `docs/ai/`. To restore the tooling in a fresh clone:

```bash
npx ai-devkit@latest init -a -e claude --built-in --yes
```

## Credits

- [`jsoosiah/htp1-custom-controller`](https://github.com/jsoosiah/htp1-custom-controller) — a
  custom web UI for the HTP-1, and the most complete public description of the MSO document.
- [`ross/ha-monoprice-htp1`](https://github.com/ross/ha-monoprice-htp1) — an earlier Home
  Assistant integration for this processor, used as a reference.

## License

MIT — see [LICENSE](LICENSE).
