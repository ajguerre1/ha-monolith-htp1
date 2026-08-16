"""Sending changes: the read-only interlock, the write contract, and the 50 ms queue.

Five processors are live in an occupied home, so the first thing this file establishes is that
a client refuses to write unless someone explicitly asked for a writable one. That makes the
"only the lab unit may be written to" rule a property of the code rather than a rule somebody
has to remember while writing a scratch script.

The queue exists because the unit's own web client does the same thing: operations are
collected for 50 ms and flushed as one `changemso`, with a later value replacing an earlier one
on the same path. That is what keeps a volume slider drag from becoming a message per pixel.

The guard on top of it is what keeps a *stationary* control from writing at all. Holding a
volume ramp against the end of the range once rewrote the same dB roughly six hundred times in
ten seconds, because nothing checked whether the value had actually changed.

Note the scope split. Here the guard compares against the mirror plus anything still queued.
Values that have been *sent but not yet confirmed* need the pending overlay, which arrives with
the reconcile watchdog in T7b.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fakes import FakeSession, FakeWebSocket, RecordingSleeper, text

from custom_components.ha_monolith_htp1.htp1.client import Htp1Client, Htp1WriteError

DOCUMENT = (
    'mso {"volume":-25,"muted":false,"powerIsOn":true,"loudness":"off",'
    '"input":"h1","cal":{"vpl":-50,"vph":0,"lipsync":40},"upmix":{"select":"native"},'
    '"status":{"SurroundMode":"Native Dolby ATMOS"}}'
)


async def _settle(times: int = 30) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


async def _started(*, allow_writes: bool = True) -> tuple[Htp1Client, FakeWebSocket]:
    socket = FakeWebSocket([text(DOCUMENT)])
    socket.hold_open = True
    client = Htp1Client(
        FakeSession([socket]),
        "10.0.0.1",
        seed="test",
        allow_writes=allow_writes,
        sleep=RecordingSleeper(),
    )
    await client.async_start()
    return client, socket


def _changes(socket: FakeWebSocket) -> list[list[dict]]:
    """Every `changemso` the client sent, decoded to its operation list."""
    return [json.loads(m.partition(" ")[2]) for m in socket.sent if m.startswith("changemso ")]


# --------------------------------------------------------------------------------------
# The read-only interlock
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("/volume", -30),
        ("/muted", True),
        ("/powerIsOn", False),
        ("/input", "h2"),
        ("/upmix/select", "dolby"),
        ("/loudness", True),
        ("/cal/lipsync", 100),
    ],
)
async def test_a_read_only_client_refuses_every_write(path, value):
    """AC-18. The safety interlock is worthless if it fails quietly."""
    client, socket = await _started(allow_writes=False)

    with pytest.raises(Htp1WriteError):
        await client.async_write(path, value)

    await _settle()
    assert _changes(socket) == [], "nothing may reach the socket from a read-only client"
    await client.async_stop()


async def test_a_read_only_client_still_reads():
    """Read-only is not inert: observing is the whole point of a probe."""
    client, socket = await _started(allow_writes=False)
    socket.feed(text('msoupdate [{"op":"replace","path":"/volume","value":-31}]'))
    await _settle()
    assert client.mirror.get("volume") == -31
    await client.async_stop()


async def test_writes_are_opt_in():
    assert Htp1Client(FakeSession(), "10.0.0.1").allow_writes is False


# --------------------------------------------------------------------------------------
# The write contract
# --------------------------------------------------------------------------------------


async def test_writing_while_disconnected_raises():
    """AC-20. Queueing would deliver the command minutes later, into a changed room."""
    client = Htp1Client(FakeSession(), "10.0.0.1", allow_writes=True)
    with pytest.raises(Htp1WriteError):
        await client.async_write("/volume", -30)


async def test_writing_an_unknown_path_raises():
    """The unit rejects an entire `changemso` if one operation targets a missing member.

    So one bad path would silently void every other write coalesced into that flush.
    """
    client, socket = await _started()
    with pytest.raises(Htp1WriteError):
        await client.async_write("/nonsense", 1)
    await _settle()
    assert _changes(socket) == []
    await client.async_stop()


async def test_writing_a_read_only_path_raises():
    """`/status/*` is what the unit reports, not something to set."""
    client, _ = await _started()
    with pytest.raises(Htp1WriteError):
        await client.async_write("/status/SurroundMode", "Stereo")
    await client.async_stop()


async def test_writing_none_raises():
    """No path here takes a null, and None is also the queue's "not queued" sentinel."""
    client, _ = await _started()
    with pytest.raises(Htp1WriteError):
        await client.async_write("/volume", None)
    await client.async_stop()


async def test_writing_the_value_already_there_is_not_an_error():
    """AC-02. It returns successfully having sent nothing, rather than raising."""
    client, socket = await _started()
    await client.async_write("/volume", -25)  # the document already says -25
    await _settle()
    assert _changes(socket) == []
    await client.async_stop()


# --------------------------------------------------------------------------------------
# The already-there guard
# --------------------------------------------------------------------------------------


async def test_six_hundred_identical_writes_send_nothing():
    """The regression that motivated the guard.

    A ramp held against the end of the range rewrote the same dB about six hundred times over a
    ten-second hold, because nothing compared the new value with the current one.
    """
    client, socket = await _started()
    for _ in range(600):
        await client.async_write("/volume", -25)
    await _settle()
    assert _changes(socket) == []
    await client.async_stop()


async def test_the_guard_compares_against_the_queue_not_just_the_mirror():
    """A second write of a value already queued must not add an operation.

    The mirror still says -25 at this point; only the queue knows about -30.
    """
    client, socket = await _started()
    await client.async_write("/volume", -30)
    await client.async_write("/volume", -30)
    await _settle()

    changes = _changes(socket)
    assert len(changes) == 1
    assert changes[0] == [{"op": "replace", "path": "/volume", "value": -30}]
    await client.async_stop()


async def test_a_genuine_change_is_sent():
    client, socket = await _started()
    await client.async_write("/volume", -30)
    await _settle()
    assert _changes(socket) == [[{"op": "replace", "path": "/volume", "value": -30}]]
    await client.async_stop()


# --------------------------------------------------------------------------------------
# Coalescing
# --------------------------------------------------------------------------------------


async def test_writes_to_one_path_coalesce_to_the_last_value():
    """AC-05. The vendor's own web client does exactly this."""
    client, socket = await _started()
    for db in (-30, -31, -32, -33):
        await client.async_write("/volume", db)
    await _settle()

    changes = _changes(socket)
    assert len(changes) == 1
    assert changes[0] == [{"op": "replace", "path": "/volume", "value": -33}]
    await client.async_stop()


async def test_writes_to_different_paths_share_one_message():
    client, socket = await _started()
    await client.async_write("/volume", -30)
    await client.async_write("/muted", True)
    await _settle()

    changes = _changes(socket)
    assert len(changes) == 1
    assert [op["path"] for op in changes[0]] == ["/volume", "/muted"]
    await client.async_stop()


async def test_a_burst_produces_exactly_one_message():
    client, socket = await _started()
    for n in range(100):
        await client.async_write("/volume", -30 - (n % 10))
    await _settle()
    assert len(_changes(socket)) == 1
    await client.async_stop()


async def test_write_many_is_one_message():
    client, socket = await _started()
    await client.async_write_many({"/volume": -30, "/muted": True})
    await _settle()
    assert len(_changes(socket)) == 1
    await client.async_stop()


async def test_a_flush_with_nothing_to_say_sends_nothing():
    """AC-06. An empty operation array is a protocol error at the unit."""
    client, socket = await _started()
    await client.async_write_many({})
    await _settle()
    assert _changes(socket) == []
    await client.async_stop()


async def test_only_replace_operations_are_emitted():
    """AC-07. A stored `test` replayed as a `replace` would execute rather than check."""
    client, socket = await _started()
    await client.async_write("/volume", -30)
    await client.async_write("/muted", True)
    await _settle()
    for change in _changes(socket):
        assert all(op["op"] == "replace" for op in change)
    await client.async_stop()


# --------------------------------------------------------------------------------------
# Encoding
# --------------------------------------------------------------------------------------


async def test_a_string_valued_switch_goes_out_as_a_string():
    """`/loudness` is "on"/"off" on the wire, not a JSON boolean."""
    client, socket = await _started()
    await client.async_write("/loudness", True)
    await _settle()
    assert _changes(socket)[0] == [{"op": "replace", "path": "/loudness", "value": "on"}]
    await client.async_stop()


async def test_a_boolean_switch_goes_out_as_a_boolean():
    client, socket = await _started()
    await client.async_write("/muted", True)
    await _settle()
    assert _changes(socket)[0] == [{"op": "replace", "path": "/muted", "value": True}]
    await client.async_stop()


# --------------------------------------------------------------------------------------
# Disconnection
# --------------------------------------------------------------------------------------


async def test_the_queue_does_not_survive_a_disconnect():
    """AC-10. Anything queued belongs to a conversation that no longer exists.

    Replaying it after a reconnect applies a stale command minutes later, into a room whose
    state has moved on.
    """
    first = FakeWebSocket([text(DOCUMENT)])
    first.hold_open = True
    second = FakeWebSocket([text(DOCUMENT)])
    second.hold_open = True
    client = Htp1Client(
        FakeSession([first, second]),
        "10.0.0.1",
        seed="test",
        allow_writes=True,
        sleep=RecordingSleeper(),
        flush_delay=10.0,  # long enough that nothing flushes before the drop
    )
    await client.async_start()

    await client.async_write("/volume", -30)
    await first.close()
    await _settle(100)

    assert _changes(second) == [], "a queued write must not be replayed onto a new connection"
    await client.async_stop()
