"""Optimistic writes: the pending overlay, and the watchdog that undoes them.

A slider has to move the moment it is dragged, but the unit's value is the truth. The client
squares that by showing the requested value immediately and re-reading if the unit never
confirms it.

The part that is easy to get wrong is *where* the optimistic value lives. Writing it into the
mirror is the obvious implementation and it has a rollback bug: if a genuine push for that path
arrives while the write is unconfirmed, restoring the "previous" value clobbers the newer truth.
Keeping pending values in a separate overlay makes rollback a deletion instead — there is
nothing stale to put back, so the bug cannot be written.

Two consequences fall out of that. Confirmation is **by value, not by acknowledgement**, because
`changemso` has no reply: a path leaves the overlay when any push arrives for it, and if the unit
clamped the request the entity settles on the unit's answer.

The second corrects the design, which predicted that a confirming push would produce an empty
change set and therefore no notification. It does not: the optimistic value never lived in the
mirror, so the mirror really does move when the push lands. What holds instead is the property
that actually matters — the value an entity reads is identical either side of a confirmation, so
a change-gated entity writes no state and nothing reaches the wall panels.

Nothing here waits on a real clock. The reconcile delay is held by the fake sleeper and released
when a test wants the watchdog to fire.
"""

from __future__ import annotations

import asyncio
import json

from fakes import FakeSession, FakeWebSocket, RecordingSleeper, text

from custom_components.ha_monolith_htp1.htp1.client import (
    DEFAULT_RECONCILE_DELAY,
    Htp1Client,
)

DOCUMENT = 'mso {"volume":-25,"muted":false,"powerIsOn":true,"cal":{"vpl":-50,"vph":0}}'


async def _settle(times: int = 40) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


async def _started(**kwargs) -> tuple[Htp1Client, FakeWebSocket, RecordingSleeper]:
    """A connected, writable client whose reconcile timer is held until released."""
    socket = FakeWebSocket([text(DOCUMENT)])
    socket.hold_open = True
    sleeper = RecordingSleeper(hold={DEFAULT_RECONCILE_DELAY})
    client = Htp1Client(
        FakeSession([socket]),
        "10.0.0.1",
        seed="test",
        allow_writes=True,
        sleep=sleeper,
        **kwargs,
    )
    await client.async_start()
    return client, socket, sleeper


def _changes(socket: FakeWebSocket) -> list[list[dict]]:
    return [json.loads(m.partition(" ")[2]) for m in socket.sent if m.startswith("changemso ")]


def _get_mso_count(socket: FakeWebSocket) -> int:
    return socket.sent.count("getmso")


# --------------------------------------------------------------------------------------
# The overlay
# --------------------------------------------------------------------------------------


async def test_an_optimistic_write_notifies_immediately():
    """What makes a slider feel instant. The mirror has not moved yet."""
    client, _socket, _ = await _started()
    heard: list[frozenset[str]] = []
    client.add_listener(heard.append)

    await client.async_write("/volume", -30)
    await _settle()

    assert heard == [frozenset({"volume"})]
    assert client.optimistic("/volume") == -30
    assert client.mirror.get("volume") == -25, "device truth must not have moved"
    await client.async_stop()


async def test_the_guard_compares_the_optimistic_value_not_the_confirmed_one():
    """With a write still unconfirmed, writing the same value again must send nothing.

    Comparing device truth instead would let a stream of identical writes through for as long
    as confirmation takes, which is most of what the guard exists to stop.
    """
    client, socket, _ = await _started()
    await client.async_write("/volume", -30)
    await _settle()
    assert len(_changes(socket)) == 1

    for _ in range(50):
        await client.async_write("/volume", -30)
    await _settle()

    assert len(_changes(socket)) == 1, "the value is already pending; nothing more should go out"
    await client.async_stop()


async def test_a_confirming_push_clears_the_pending_value():
    client, socket, _ = await _started()
    await client.async_write("/volume", -30)
    await _settle()
    assert client.pending_paths == ("/volume",)

    socket.feed(text('msoupdate [{"op":"replace","path":"/volume","value":-30}]'))
    await _settle()

    assert client.pending_paths == ()
    assert client.mirror.get("volume") == -30
    await client.async_stop()


async def test_a_confirming_push_does_not_change_what_entities_see():
    """The design predicted no notification here. That was wrong, and the reason is instructive.

    The optimistic value never lived in the mirror, so when the confirming push arrives the
    mirror genuinely *does* move — from the old value to the new one — and the change set is
    not empty. The client therefore notifies.

    What actually holds is the property that matters: the value entities read is identical
    before and after, so a change-gated entity writes no state and nothing reaches the wall
    panels. The zero-cost guarantee comes from the entity snapshot compare, not from an empty
    change set here.
    """
    client, socket, _ = await _started()
    await client.async_write("/volume", -30)
    await _settle()

    heard: list[frozenset[str]] = []
    client.add_listener(heard.append)
    before = client.optimistic("/volume")
    socket.feed(text('msoupdate [{"op":"replace","path":"/volume","value":-30}]'))
    await _settle()

    assert client.optimistic("/volume") == before == -30, (
        "what an entity reads must not move across a confirmation"
    )
    assert heard == [frozenset({"volume"})], "the client does notify; the entity gates it"
    await client.async_stop()


async def test_a_clamped_value_settles_on_the_units_answer():
    """`changemso` has no reply, so confirmation is by value rather than acknowledgement.

    If the unit clamps or ignores the request, the push carries something else, the overlay
    clears anyway, and the entity ends up showing what the unit actually did.
    """
    client, socket, _ = await _started()
    heard: list[frozenset[str]] = []

    await client.async_write("/volume", -80)  # below this unit's floor of -50
    await _settle()
    client.add_listener(heard.append)

    socket.feed(text('msoupdate [{"op":"replace","path":"/volume","value":-50}]'))
    await _settle()

    assert client.pending_paths == ()
    assert client.optimistic("/volume") == -50
    assert heard == [frozenset({"volume"})], "the correction must reach the entities"
    await client.async_stop()


async def test_a_container_push_confirms_the_leaves_beneath_it():
    client, socket, _ = await _started()
    await client.async_write("/cal/lipsync", 120)
    await _settle()
    assert client.pending_paths == ("/cal/lipsync",)

    socket.feed(text('msoupdate [{"op":"replace","path":"/cal","value":{"lipsync":120}}]'))
    await _settle()

    assert client.pending_paths == ()
    await client.async_stop()


async def test_a_full_document_confirms_everything():
    client, socket, _ = await _started()
    await client.async_write("/volume", -30)
    await client.async_write("/muted", True)
    await _settle()
    assert len(client.pending_paths) == 2

    socket.feed(text(DOCUMENT))
    await _settle()

    assert client.pending_paths == ()
    await client.async_stop()


# --------------------------------------------------------------------------------------
# The watchdog
# --------------------------------------------------------------------------------------


async def test_an_unconfirmed_write_is_rolled_back_and_re_read():
    client, socket, sleeper = await _started()
    before = _get_mso_count(socket)

    await client.async_write("/volume", -30)
    await _settle()
    assert client.optimistic("/volume") == -30

    sleeper.release(DEFAULT_RECONCILE_DELAY)
    await _settle()

    assert client.pending_paths == ()
    assert client.optimistic("/volume") == -25, "the optimistic value must be given up"
    assert _get_mso_count(socket) == before + 1, "and the document re-requested"
    await client.async_stop()


async def test_a_rollback_notifies_so_entities_stop_showing_the_optimistic_value():
    """Otherwise a slider sits at a position the unit never adopted, with no correction."""
    client, _socket, sleeper = await _started()
    await client.async_write("/volume", -30)
    await _settle()

    heard: list[frozenset[str]] = []
    client.add_listener(heard.append)
    sleeper.release(DEFAULT_RECONCILE_DELAY)
    await _settle()

    assert heard and "volume" in heard[0]
    await client.async_stop()


async def test_a_rollback_does_not_clobber_a_newer_push():
    """The bug that writing optimistic values into the mirror would cause.

    Write -30, then a genuine push says -35 before confirmation. The push clears the overlay,
    so there is no rollback to perform and nothing stale to restore. The value must stay -35.
    """
    client, socket, sleeper = await _started()
    await client.async_write("/volume", -30)
    await _settle()

    socket.feed(text('msoupdate [{"op":"replace","path":"/volume","value":-35}]'))
    await _settle()

    sleeper.release(DEFAULT_RECONCILE_DELAY)
    await _settle()

    assert client.optimistic("/volume") == -35
    assert client.mirror.get("volume") == -35
    await client.async_stop()


async def test_a_confirming_push_cancels_the_watchdog():
    client, socket, sleeper = await _started()
    await client.async_write("/volume", -30)
    await _settle()

    socket.feed(text('msoupdate [{"op":"replace","path":"/volume","value":-30}]'))
    await _settle()

    before = _get_mso_count(socket)
    sleeper.release(DEFAULT_RECONCILE_DELAY)
    await _settle()

    assert _get_mso_count(socket) == before, "a cancelled watchdog must not re-read"
    await client.async_stop()


async def test_the_reconcile_deadline_is_re_armed_per_flush():
    """A later write gets its full grace period, not the remainder of an earlier one.

    Inheriting the first deadline would give the second write less time to be confirmed than
    the unit is allowed to take.
    """
    client, _socket, sleeper = await _started()
    await client.async_write("/volume", -30)
    await _settle()
    first = sleeper.delays.count(DEFAULT_RECONCILE_DELAY)

    await client.async_write("/muted", True)
    await _settle()

    assert sleeper.delays.count(DEFAULT_RECONCILE_DELAY) == first + 1, (
        "the second flush must start its own reconcile window"
    )
    await client.async_stop()


async def test_the_watchdog_reset_restores_the_parse_budget():
    """The reconcile is a deliberate re-request, so it is one of the three legitimate resets."""
    client, socket, sleeper = await _started()
    socket.feed(text("mso {not json"))
    await _settle()
    assert client._parse_failures == 1

    await client.async_write("/volume", -30)
    await _settle()
    sleeper.release(DEFAULT_RECONCILE_DELAY)
    await _settle()

    assert client._parse_failures == 0
    await client.async_stop()


async def test_a_disconnect_drops_pending_values_too():
    """They belong to a conversation that no longer exists, exactly like the queue."""
    client, socket, _ = await _started()
    await client.async_write("/volume", -30)
    await _settle()
    assert client.pending_paths == ("/volume",)

    await socket.close()
    await _settle(100)

    assert client.pending_paths == ()
    await client.async_stop()


async def test_the_reconcile_delay_is_two_seconds():
    assert DEFAULT_RECONCILE_DELAY == 2.0
