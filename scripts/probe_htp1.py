"""Read-only probe for a Monolith HTP-1. Never writes.

    python scripts/probe_htp1.py summary 192.168.1.50      # placeholder, not a real address
    python scripts/probe_htp1.py observe 192.168.1.50 --seconds 120
    python scripts/probe_htp1.py summary 192.168.1.50 --raw

`summary` connects, asks for the document once, prints a scrubbed digest and disconnects.
`observe` holds the connection open and prints pushes as they arrive, which is how you confirm
that a front-panel change reaches Home Assistant without anything being requested.

**This tool cannot write.** It never constructs a write-enabled client and never calls a write
method, and `tests/test_probe.py` parses this file to keep it that way. Reading is provably
passive: an idle connection to one of these units sent zero bytes over ninety seconds, and the
unit serves concurrent controller connections independently, so probing does not disturb the
web UI or anyone using the room.

**The digest is scrubbed by default.** A real `mso` document carries the unit's name, the
owner's input labels, their Dirac slot names and the serial number. That is site data, so the
summary reports counts and shapes rather than names. `--raw` writes the full document to
`scripts/output/`, which is gitignored, and says so.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import aiohttp  # noqa: E402

from custom_components.ha_monolith_htp1.htp1 import protocol  # noqa: E402
from custom_components.ha_monolith_htp1.htp1.client import (  # noqa: E402
    WS_PATH,
    Htp1Client,
    Htp1Error,
)
from custom_components.ha_monolith_htp1.htp1.mso import TRACKED_PATHS, MsoMirror  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "scripts" / "output"

_MAC = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "null"
    return type(value).__name__


def _find_macs(node: Any, path: str = "") -> list[str]:
    """Every path holding something shaped like a MAC address. Paths only, never values.

    HW-03 asks whether the document carries a MAC at all, because that decides whether Home
    Assistant's DHCP discovery can track a unit across an address change. The address itself is
    still site data.
    """
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found += _find_macs(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found += _find_macs(value, f"{path}/{index}")
    elif isinstance(node, str) and _MAC.match(node):
        found.append(path)
    return found


def summarise(document: dict[str, Any]) -> dict[str, Any]:
    """A scrubbed digest of one document. Pure, so it is testable against fixtures.

    Deliberately reports counts and types rather than names and values wherever the value would
    be the owner's rather than the unit's.
    """
    cal = document.get("cal") or {}
    versions = document.get("versions") or {}
    inputs = document.get("inputs") or {}
    slots = cal.get("slots") or []
    status = document.get("status") or {}

    tracked_present = sorted(
        path for path in TRACKED_PATHS if _resolve(document, path) is not _MISSING
    )

    return {
        "firmware": {
            "swVer": versions.get("swVer"),
            "avController": (versions.get("avController") or "").split()[0] or None
            if versions.get("avController")
            else None,
            "serial_present": bool(versions.get("SerialNumber")),
        },
        # HW-04. The whole volume map derives from these, and they are user-configurable.
        "volume_range": {"vpl": cal.get("vpl"), "vph": cal.get("vph")},
        # HW-02. Declared bool in the mirror, never measured on real firmware until now.
        "eq_tc": {
            "present": "tc" in (document.get("eq") or {}),
            "json_type": _json_type((document.get("eq") or {}).get("tc")),
        },
        # HW-03.
        "mac_addresses_found": _find_macs(document),
        # HW-07. The unit's own vocabulary, which is device behaviour rather than site data.
        "status_vocabulary": {k: v for k, v in status.items() if k != "raw" and v is not None},
        "videostat_present": "videostat" in document,
        "inputs": {
            "total": len(inputs),
            "visible": sum(1 for i in inputs.values() if isinstance(i, dict) and i.get("visible")),
            "labelled": sum(1 for i in inputs.values() if isinstance(i, dict) and i.get("label")),
        },
        "dirac_slots": {
            "total": len(slots),
            "named": sum(1 for s in slots if isinstance(s, dict) and s.get("name")),
            "current": cal.get("currentdiracslot"),
            "active": cal.get("diracactive"),
        },
        "two_state_paths": {
            path: _json_type(_resolve(document, path))
            for path in ("/loudness", "/bassenhance", "/muted", "/powerIsOn", "/eq/tc")
            if _resolve(document, path) is not _MISSING
        },
        "tracked_paths_present": len(tracked_present),
        "tracked_paths_absent": sorted(set(TRACKED_PATHS) - set(tracked_present)),
        "document_bytes": len(json.dumps(document)),
        "top_level_keys": sorted(document),
    }


_MISSING = object()


def _resolve(document: Any, pointer: str) -> Any:
    node = document
    for part in pointer.strip("/").split("/"):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


async def _read_document(host: str, port: int, timeout: float) -> dict[str, Any] | None:
    """One `getmso`, straight off the wire. Read-only, and nothing is ever sent but that verb.

    This deliberately does not go through `Htp1Client`. The client keeps a *projection* of the
    document — about thirty leaves out of a 47 KB object — which is the whole point of it, and
    exactly the wrong thing for a tool whose job is to report what the unit actually sent,
    including keys this integration has never heard of.
    """
    url = f"ws://{host}:{port}{WS_PATH}"
    async with aiohttp.ClientSession() as session:
        async with asyncio.timeout(timeout):
            async with session.ws_connect(url, heartbeat=30.0) as ws:
                await ws.send_str(protocol.encode_get_mso())
                while True:
                    message = await ws.receive()
                    if message.type is not aiohttp.WSMsgType.TEXT:
                        return None
                    parsed = protocol.parse_message(message.data)
                    if parsed.kind is protocol.MessageKind.DOCUMENT:
                        return parsed.document


async def _summary(host: str, port: int, raw: bool) -> int:
    try:
        document = await _read_document(host, port, timeout=20.0)
    except (TimeoutError, OSError, aiohttp.ClientError) as err:
        print(f"could not read {host}: {err}", file=sys.stderr)
        return 1

    if not document:
        print(f"{host} answered, but not with a document", file=sys.stderr)
        return 1

    print(json.dumps(summarise(document), indent=2, sort_keys=True))

    # Report a declared codec that disagrees with what this unit actually sent (HW-02).
    mirror = MsoMirror()
    mirror.apply_document(document)
    if mirror.mismatches:
        print(
            f"\nCODEC MISMATCH: {list(mirror.mismatches)} — the declared wire shape disagrees "
            f"with what this unit sent",
            file=sys.stderr,
        )

    if raw:
        path = _write_raw(host, document)
        print(f"\nraw document written to {path}", file=sys.stderr)
        print("it contains site data and is gitignored; do not paste it", file=sys.stderr)
    return 0


def _write_raw(host: str, document: dict[str, Any]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_host = re.sub(r"[^A-Za-z0-9_.-]", "_", host)
    path = OUTPUT_DIR / f"{safe_host}-{stamp}.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    return path


async def _observe(host: str, port: int, seconds: float) -> int:
    async with aiohttp.ClientSession() as session:
        client = Htp1Client(session, host, port=port, seed=host)
        try:
            await client.async_start()
        except Htp1Error as err:
            print(f"could not read {host}: {err}", file=sys.stderr)
            return 1

        started = asyncio.get_running_loop().time()
        count = 0

        def on_change(changed: frozenset[str]) -> None:
            nonlocal count
            count += 1
            elapsed = asyncio.get_running_loop().time() - started
            # Field names, not values: a value could be an input label.
            print(f"[{elapsed:7.1f}s] changed: {', '.join(sorted(changed))}", flush=True)

        client.add_listener(on_change)
        print(f"observing {host} for {seconds:.0f}s — change something on the front panel")
        try:
            await asyncio.sleep(seconds)
        finally:
            await client.async_stop()
        print(f"\n{count} push(es) in {seconds:.0f}s")
        if count == 0:
            print("an idle unit sending nothing is the expected result; this is why we never poll")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only probe for a Monolith HTP-1.")
    parser.add_argument("mode", choices=("summary", "observe"))
    parser.add_argument("host")
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--seconds", type=float, default=120.0, help="observe mode only")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="also write the full document to scripts/output/ (gitignored, contains site data)",
    )
    args = parser.parse_args()

    if args.mode == "summary":
        return asyncio.run(_summary(args.host, args.port, args.raw))
    return asyncio.run(_observe(args.host, args.port, args.seconds))


if __name__ == "__main__":
    raise SystemExit(main())
