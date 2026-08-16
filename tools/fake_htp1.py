"""A local stand-in for a Monolith HTP-1, with fault injection.

Speaks the real protocol from an invented document, so the client can be exercised over a real
socket without a processor present. Run it standalone, or drive it from tests:

    python tools/fake_htp1.py                        # serve on 127.0.0.1, ephemeral port
    python tools/fake_htp1.py --port 8080
    python tools/fake_htp1.py --fault accept-tcp-no-upgrade
    python tools/fake_htp1.py --list-faults

**The fault that matters most is `accept-tcp-no-upgrade`.** It is the only way to prove the 15 s
handshake timeout fires, and the defect it models — a unit binding port 80 while it is still
booting, before `/ws/controller` is live — wedged an earlier driver for this same processor
permanently, until someone reloaded it by hand.

The document here is invented. A real `mso` carries the owner's unit name, input labels, Dirac
slot names and serial number, and this repository is public.

Two faults from the earlier driver are deliberately absent. `trickle` (one byte per write) and
`drop-mid-frame` tested RFC 6455 fragment reassembly, which that driver needed because it
hand-wrote its own codec. Here aiohttp owns framing, so those faults would be testing aiohttp
rather than anything in this repository. The same applies to suppressing a pong: the pong
deadline is aiohttp's, derived from `heartbeat`. `close-after-document` covers the recovery path
those would have reached.

Note the module name uses an underscore, unlike the Lua project's `fake-htp1.py`, so that the
integration tests can import it rather than shelling out.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

WS_PATH = "/ws/controller"

FAULTS = {
    "accept-tcp-no-upgrade": "Accept the TCP connection and never complete the handshake.",
    "garbage": "Answer getmso with something undecodable.",
    "bare-json": "Send payloads with no verb prefix, as newer firmware reportedly does.",
    "never-confirm": "Accept changemso, do nothing, and say nothing. The silently ignored write.",
    "container-replace": "Echo changes as whole-subtree replaces instead of leaf replaces.",
    "no-videostat": "Report a document with no video block, like firmware 1.13.x.",
    "no-serial": "Report a document with no serial number.",
    "close-after-document": "Hang up immediately after answering the first getmso.",
}


def default_document() -> dict[str, Any]:
    """An invented document, shaped like firmware 2.x. Nothing here came off a real unit."""
    return {
        "unitname": "Fake Processor",
        "powerIsOn": True,
        "powerAction": "none",
        "volume": -25,
        "muted": False,
        "input": "h1",
        "loudness": "off",
        "bassenhance": "off",
        "night": "auto",
        "dialogEnh": 2,
        "eq": {"tc": False},
        "inputs": {
            "h1": {"label": "Media Player", "visible": True},
            "h2": {"label": "Game Console", "visible": True},
            "a1": {"label": "Turntable", "visible": True},
            "tv": {"label": "Television", "visible": True},
        },
        "upmix": {
            "select": "native",
            "off": {"homevis": True},
            "native": {"homevis": True},
            "dolby": {"homevis": True},
            "dts": {"homevis": True},
            "auro": {"homevis": False},
            "mono": {"homevis": False},
            "stereo": {"homevis": True},
        },
        "cal": {
            "vpl": -50,
            "vph": 0,
            "lipsync": 40,
            "currentdiracslot": 1,
            "diracactive": "on",
            "slots": [
                {"name": "Reference"},
                {"name": "Movie Night"},
                {"name": ""},
                {"name": "Music"},
                {"name": "Late Night"},
                {"name": "Calibration Test"},
            ],
        },
        "status": {
            "SurroundMode": "Native Dolby ATMOS",
            "DECSourceProgram": "Dolby MAT/PCM",
            "DECProgramFormat": "Object Audio",
            "DECSampleRate": "48 kHz",
            "ENCListeningFormat": "5.1.2",
            "ENCSampleRate": "48 kHz",
            "DiracState": "on",
            "raw": {"activityMask": 0, "formatCode": 17},
        },
        "videostat": {
            "VideoResolution": "3840x2160p60Hz",
            "VideoColorSpace": "BT2020",
            "HDRstatus": "HDR10",
        },
        "versions": {
            "avController": "5.96 Built Jul  8 2026, 11:45:00\n",
            "swVer": "V2.1.1",
            "SerialNumber": "TESTSN9999",
        },
    }


class FakeHtp1:
    """One fake processor. Use as an async context manager, or call `start`/`stop`."""

    def __init__(
        self,
        *,
        faults: set[str] | None = None,
        document: dict[str, Any] | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self.faults = set(faults or ())
        unknown = self.faults - set(FAULTS)
        if unknown:
            raise ValueError(f"unknown fault(s): {sorted(unknown)}")

        self.document = document if document is not None else default_document()
        if "no-videostat" in self.faults:
            self.document.pop("videostat", None)
        if "no-serial" in self.faults:
            self.document.get("versions", {}).pop("SerialNumber", None)

        self.host = host
        self.port = port
        self.received: list[str] = []
        self._clients: set[ServerConnection] = set()
        self._server: Any = None
        self._raw_server: asyncio.Server | None = None
        # The hanging handler waits on this rather than on a never-set event. Since Python
        # 3.12, `Server.wait_closed()` waits for handler tasks to finish, so a handler that
        # never returns hangs shutdown - and with it any test suite that stops the fake.
        self._shutdown: asyncio.Event | None = None

    async def __aenter__(self) -> FakeHtp1:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    async def start(self) -> int:
        """Begin serving. Returns the port actually bound."""
        if "accept-tcp-no-upgrade" in self.faults:
            # A raw TCP listener that accepts and then says nothing at all. This is the unit
            # with its web server up but /ws/controller not yet live.
            self._shutdown = asyncio.Event()
            self._raw_server = await asyncio.start_server(self._hang, self.host, self.port)
            self.port = self._raw_server.sockets[0].getsockname()[1]
            return self.port

        self._server = await serve(self._handle, self.host, self.port).__aenter__()
        self.port = next(iter(self._server.sockets)).getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self._raw_server is not None:
            # Release the hanging handlers first, or `wait_closed()` waits for them forever.
            if self._shutdown is not None:
                self._shutdown.set()
            self._raw_server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._raw_server.wait_closed(), timeout=2.0)
            self._raw_server = None
            self._shutdown = None
        if self._server is not None:
            with contextlib.suppress(Exception):
                await self._server.__aexit__(None, None, None)
            self._server = None

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}{WS_PATH}"

    async def _hang(self, _reader: Any, writer: Any) -> None:
        """Accept, then say nothing until the fake is stopped.

        From the client's side this is indistinguishable from a unit whose web server has bound
        the port but whose `/ws/controller` route is not live yet.
        """
        try:
            if self._shutdown is not None:
                await self._shutdown.wait()
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    async def _handle(self, ws: ServerConnection) -> None:
        # The real unit enforces the path; anything else is closed with a policy violation.
        if ws.request.path != WS_PATH:
            await ws.close(code=1008, reason="unknown path")
            return

        self._clients.add(ws)
        try:
            async for raw in ws:
                self.received.append(raw)
                await self._on_message(ws, raw)
        except Exception:
            pass
        finally:
            self._clients.discard(ws)

    async def _on_message(self, ws: ServerConnection, raw: str) -> None:
        verb, _, payload = raw.partition(" ")

        if verb == "getmso":
            await self._send_document(ws)
            if "close-after-document" in self.faults:
                await ws.close()
            return

        if verb == "changemso":
            await self._apply(payload)
            return

        # Junk input is answered, and the connection survives.
        await ws.send('error "bad-verb"')

    async def _send_document(self, ws: ServerConnection) -> None:
        if "garbage" in self.faults:
            await ws.send("mso {not json")
            return
        body = json.dumps(self.document, separators=(",", ":"))
        await ws.send(body if "bare-json" in self.faults else f"mso {body}")

    async def _apply(self, payload: str) -> None:
        try:
            ops = json.loads(payload)
        except ValueError:
            return
        if not isinstance(ops, list):
            return

        if "never-confirm" in self.faults:
            # Deliberately does not apply the change either. A unit that applied it silently
            # would leave the client's optimistic value *correct*, so the watchdog would have
            # nothing to correct and the test would prove nothing. The interesting fault is the
            # write that is dropped on the floor.
            return

        applied = []
        for op in ops:
            if not isinstance(op, dict) or op.get("op") != "replace":
                continue
            if _set_pointer(self.document, op["path"], op.get("value")):
                applied.append(op)

        if applied and "never-confirm" not in self.faults:
            await self.broadcast(applied)

    async def broadcast(self, ops: list[dict[str, Any]]) -> None:
        """Echo operations to every connected client, as the real unit does."""
        if "container-replace" in self.faults:
            ops = _as_container_replaces(self.document, ops)
        body = json.dumps(ops, separators=(",", ":"))
        message = body if "bare-json" in self.faults else f"msoupdate {body}"
        for client in list(self._clients):
            with contextlib.suppress(Exception):
                await client.send(message)


def _set_pointer(document: dict[str, Any], pointer: str, value: Any) -> bool:
    """Apply one JSON-pointer assignment. Returns False if the member does not exist.

    The real unit rejects a whole `changemso` when an operation targets a missing member; this
    only declines the individual operation, which is enough to notice the mistake in a test.
    """
    parts = [p for p in pointer.split("/") if p]
    if not parts:
        return False
    node: Any = document
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        return False
    node[parts[-1]] = value
    return True


def _as_container_replaces(document: dict[str, Any], ops: list[dict]) -> list[dict]:
    """Rewrite leaf replaces as replaces of the subtree above them."""
    containers: dict[str, Any] = {}
    for op in ops:
        parts = [p for p in op["path"].split("/") if p]
        if len(parts) < 2:
            containers[op["path"]] = op.get("value")
            continue
        prefix = "/" + "/".join(parts[:-1])
        containers[prefix] = document.get(parts[0]) if len(parts) == 2 else op.get("value")
    return [{"op": "replace", "path": path, "value": value} for path, value in containers.items()]


async def _serve_forever(args: argparse.Namespace) -> None:
    fake = FakeHtp1(faults=set(args.fault), host=args.host, port=args.port)
    port = await fake.start()
    # Flushed, because the usual caller is a script waiting to learn the port. Python
    # buffers stdout when it is a pipe, so an unflushed banner hangs whoever is reading.
    print(f"fake HTP-1 on ws://{args.host}:{port}{WS_PATH}", flush=True)
    if fake.faults:
        print("faults:", ", ".join(sorted(fake.faults)), flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await fake.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    parser.add_argument("--fault", action="append", default=[], choices=sorted(FAULTS))
    parser.add_argument("--list-faults", action="store_true")
    args = parser.parse_args()

    if args.list_faults:
        for name, description in sorted(FAULTS.items()):
            print(f"{name:24} {description}")
        return

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve_forever(args))


if __name__ == "__main__":
    main()
