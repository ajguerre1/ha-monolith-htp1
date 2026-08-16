"""Consuming pushes: the parse-failure budget, and telling the layers above what moved.

The budget is the subtle part, and it has a trap in the middle of it.

When the unit sends something this client cannot decode, the fastest recovery is simply asking
again. But if *every* reply is undecodable, asking again on each failure is an unthrottled
request storm aimed at a processor in daily use, plus a log line per iteration. So consecutive
failures are capped at three.

The trap is where the counter resets. It must reset when a decodable message arrives, and on a
**deliberate** re-request — a connect, the reconcile watchdog, an explicit refresh. It must
**not** reset inside the error path's own retry. Resetting there zeroes the counter on every
failure, which restores exactly the storm the cap exists to prevent, while looking correct.

The second theme is notification. Listeners hear only what actually moved: the mirror already
drops no-op assignments, and the client only calls out when the resulting change set is
non-empty. With five units feeding roughly fifty wall panels, a spurious notification is a
performance defect rather than a cosmetic one.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from fakes import FakeSession, FakeWebSocket, RecordingSleeper, text

from custom_components.ha_monolith_htp1.htp1.client import (
    MAX_PARSE_FAILURES,
    Htp1Client,
    Htp1ConnectionError,
)

DOCUMENT = 'mso {"volume":-25,"muted":false,"powerIsOn":true,"cal":{"vpl":-50,"vph":0}}'
GARBAGE = "mso {not json"


async def _settle(times: int = 30) -> None:
    """Let the supervisor task run. Nothing here waits on a real timer."""
    for _ in range(times):
        await asyncio.sleep(0)


async def _started() -> tuple[Htp1Client, FakeWebSocket]:
    socket = FakeWebSocket([text(DOCUMENT)])
    socket.hold_open = True
    client = Htp1Client(FakeSession([socket]), "10.0.0.1", seed="test", sleep=RecordingSleeper())
    await client.async_start()
    return client, socket


def _get_mso_count(socket: FakeWebSocket) -> int:
    return socket.sent.count("getmso")


# --------------------------------------------------------------------------------------
# Listeners
# --------------------------------------------------------------------------------------


async def test_a_listener_hears_what_moved():
    client, socket = await _started()
    heard: list[frozenset[str]] = []
    client.add_listener(heard.append)

    socket.feed(text('msoupdate [{"op":"replace","path":"/volume","value":-30}]'))
    await _settle()

    assert heard == [frozenset({"volume"})]
    assert client.mirror.get("volume") == -30
    await client.async_stop()


async def test_a_push_that_changes_nothing_notifies_nobody():
    """The value is already -25. Nothing moved, so nothing downstream should wake up."""
    client, socket = await _started()
    heard: list[frozenset[str]] = []
    client.add_listener(heard.append)

    socket.feed(text('msoupdate [{"op":"replace","path":"/volume","value":-25}]'))
    await _settle()

    assert heard == []
    await client.async_stop()


async def test_unsubscribing_stops_the_notifications():
    client, socket = await _started()
    heard: list[frozenset[str]] = []
    unsubscribe = client.add_listener(heard.append)

    socket.feed(text('msoupdate [{"op":"replace","path":"/volume","value":-30}]'))
    await _settle()
    unsubscribe()
    socket.feed(text('msoupdate [{"op":"replace","path":"/volume","value":-35}]'))
    await _settle()

    assert len(heard) == 1, "the second push should not have been delivered"
    assert client.mirror.get("volume") == -35, "but the mirror must still have followed it"
    await client.async_stop()


async def test_unsubscribing_twice_is_harmless():
    client, _ = await _started()
    unsubscribe = client.add_listener(lambda changed: None)
    unsubscribe()
    unsubscribe()
    await client.async_stop()


async def test_a_listener_that_raises_does_not_take_down_the_connection():
    """An entity blowing up in its callback must not cost the connection for everything else."""
    client, socket = await _started()
    survivor: list[frozenset[str]] = []

    def explode(changed):
        raise RuntimeError("entity is having a bad day")

    client.add_listener(explode)
    client.add_listener(survivor.append)

    socket.feed(text('msoupdate [{"op":"replace","path":"/volume","value":-30}]'))
    await _settle()

    assert survivor == [frozenset({"volume"})]
    assert client.connected is True
    await client.async_stop()


async def test_a_document_push_notifies_too():
    client, socket = await _started()
    heard: list[frozenset[str]] = []
    client.add_listener(heard.append)

    socket.feed(text('mso {"volume":-40,"powerIsOn":true}'))
    await _settle()

    assert heard and "volume" in heard[0]
    await client.async_stop()


# --------------------------------------------------------------------------------------
# Things that are not parse failures
# --------------------------------------------------------------------------------------


async def test_an_error_frame_does_not_spend_budget(caplog):
    """Junk input yields `error "bad-verb"` and the connection survives."""
    client, socket = await _started()
    before = _get_mso_count(socket)

    with caplog.at_level(logging.DEBUG):
        socket.feed(text('error "bad-verb"'))
        await _settle()

    assert client._parse_failures == 0
    assert _get_mso_count(socket) == before, "an error frame must not trigger a re-read"
    assert client.connected is True
    await client.async_stop()


async def test_an_unknown_shape_does_not_spend_budget():
    """Newer firmware says things this client has never heard of. That must be free."""
    client, socket = await _started()
    before = _get_mso_count(socket)

    socket.feed(text('{"somethingElse":123,"notAnOp":true}'))
    socket.feed(text("wibble {}"))
    await _settle()

    assert client._parse_failures == 0
    assert _get_mso_count(socket) == before
    await client.async_stop()


async def test_a_bare_json_push_is_applied():
    client, socket = await _started()
    socket.feed(text('[{"op":"replace","path":"/muted","value":true}]'))
    await _settle()
    assert client.mirror.get("muted") is True
    await client.async_stop()


# --------------------------------------------------------------------------------------
# The parse-failure budget
# --------------------------------------------------------------------------------------


async def test_an_undecodable_frame_triggers_one_re_read():
    client, socket = await _started()
    before = _get_mso_count(socket)

    socket.feed(text(GARBAGE))
    await _settle()

    assert client._parse_failures == 1
    assert _get_mso_count(socket) == before + 1
    await client.async_stop()


async def test_the_error_path_retry_does_not_reset_the_budget():
    """The subtlest test in the milestone.

    Re-reading is the recovery, but re-reading must not refresh the allowance that limits it.
    If it did, every failure would send another `getmso` and a unit stuck emitting undecodable
    replies would be hammered at line rate — which is exactly what happened once, against a
    processor in daily use.
    """
    client, socket = await _started()
    before = _get_mso_count(socket)

    for _ in range(10):
        socket.feed(text(GARBAGE))
    await _settle(100)

    sent = _get_mso_count(socket) - before
    assert sent == MAX_PARSE_FAILURES - 1, (
        f"expected {MAX_PARSE_FAILURES - 1} re-reads before the cap, got {sent}"
    )
    assert client._parse_failures >= MAX_PARSE_FAILURES
    await client.async_stop()


async def test_the_cap_is_logged_exactly_once(caplog):
    """Past the cap the client goes quiet, rather than a log line per undecodable frame."""
    client, socket = await _started()

    with caplog.at_level(logging.ERROR):
        for _ in range(10):
            socket.feed(text(GARBAGE))
        await _settle(100)

    giving_up = [r for r in caplog.records if "giving up" in r.getMessage()]
    assert len(giving_up) == 1
    await client.async_stop()


async def test_a_decodable_message_clears_the_streak():
    """The cap counts *consecutive* failures. One good reply means the unit is fine."""
    client, socket = await _started()

    socket.feed(text(GARBAGE))
    await _settle()
    assert client._parse_failures == 1

    socket.feed(text('msoupdate [{"op":"replace","path":"/volume","value":-31}]'))
    await _settle()

    assert client._parse_failures == 0
    await client.async_stop()


async def test_a_deliberate_refresh_restores_the_budget():
    """Without a way back, a client whose first document failed three times sits mute forever.

    The reset belongs here and in a reconnect — never in the error path's own retry.
    """
    client, socket = await _started()
    for _ in range(10):
        socket.feed(text(GARBAGE))
    await _settle(100)
    assert client._parse_failures >= MAX_PARSE_FAILURES

    before = _get_mso_count(socket)
    await client.async_refresh()

    assert client._parse_failures == 0
    assert _get_mso_count(socket) == before + 1

    # And the budget genuinely works again.
    socket.feed(text(GARBAGE))
    await _settle()
    assert _get_mso_count(socket) == before + 2
    await client.async_stop()


async def test_reconnecting_restores_the_budget():
    """A fresh connection is a fresh chance; the old failures belong to a dead conversation."""
    first = FakeWebSocket([text(DOCUMENT)])
    first.hold_open = True
    second = FakeWebSocket([text(DOCUMENT)])
    second.hold_open = True
    client = Htp1Client(
        FakeSession([first, second]), "10.0.0.1", seed="test", sleep=RecordingSleeper()
    )
    await client.async_start()

    for _ in range(10):
        first.feed(text(GARBAGE))
    await _settle(100)
    assert client._parse_failures >= MAX_PARSE_FAILURES

    await first.close()
    await _settle(100)

    assert client._parse_failures == 0
    await client.async_stop()


async def test_the_budget_is_three():
    assert MAX_PARSE_FAILURES == 3


async def test_refreshing_while_disconnected_raises():
    client = Htp1Client(FakeSession(), "10.0.0.1", seed="test")
    with pytest.raises(Htp1ConnectionError):
        await client.async_refresh()
