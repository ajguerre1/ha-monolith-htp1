"""Adding and re-addressing a processor.

The flow is the only part of this integration most users will ever consciously interact with,
and they will do it once, while something is not working. So the tests care as much about *which*
error is reported as about whether one is: "could not reach that address" and "it answered but
did not complete the connection" call for different actions from the person reading them.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ha_monolith_htp1.const import DOMAIN
from custom_components.ha_monolith_htp1.htp1.client import (
    Htp1ConnectionError,
    Htp1Error,
    Htp1TimeoutError,
)

PATCH_IDENTITY = "custom_components.ha_monolith_htp1.config_flow._read_identity"


class _Identity:
    def __init__(self, serial=None, unit_name=None):
        self.serial = serial
        self.unit_name = unit_name

    def title(self, host):
        return self.unit_name or f"Monolith HTP-1 ({host})"


async def _submit(hass, host, identity=None, error=None, flow_id=None):
    if flow_id is None:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        flow_id = result["flow_id"]
    with patch(
        PATCH_IDENTITY,
        side_effect=error,
        return_value=identity or _Identity("TESTSN0001", "Test Processor"),
    ):
        return await hass.config_entries.flow.async_configure(flow_id, {"host": host})


async def test_the_config_flow_creates_an_entry(hass):
    """AC-40."""
    result = await _submit(hass, "10.0.0.1")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Processor"
    assert result["data"] == {"host": "10.0.0.1"}
    assert result["result"].unique_id == "TESTSN0001"


@pytest.mark.parametrize(
    ("pasted", "stored"),
    [
        ("  10.0.0.1  ", "10.0.0.1"),
        ("http://10.0.0.1", "10.0.0.1"),
        ("http://10.0.0.1/", "10.0.0.1"),
        ("ws://10.0.0.1/ws/controller", "10.0.0.1"),
    ],
)
async def test_a_pasted_url_is_accepted(hass, pasted, stored):
    """People copy what is in their browser's address bar. Take it."""
    result = await _submit(hass, pasted)
    assert result["data"] == {"host": stored}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (Htp1ConnectionError("refused"), "cannot_connect"),
        (Htp1TimeoutError("no upgrade"), "timeout_connect"),
        (Htp1Error("not a document"), "not_htp1"),
        (RuntimeError("surprise"), "unknown"),
    ],
)
async def test_the_config_flow_reports_why_it_failed(hass, error, expected):
    """AC-41. Each of these calls for a different action from the person reading it."""
    result = await _submit(hass, "10.0.0.1", error=error)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_an_empty_address_is_rejected_without_a_network_call(hass):
    result = await _submit(hass, "   ")
    assert result["errors"] == {"base": "invalid_host"}


async def test_the_form_can_be_retried_after_an_error(hass):
    """An error must leave a usable form, not a dead end."""
    first = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    failed = await _submit(
        hass, "10.0.0.1", error=Htp1ConnectionError("nope"), flow_id=first["flow_id"]
    )
    assert failed["type"] is FlowResultType.FORM

    succeeded = await _submit(hass, "10.0.0.2", flow_id=first["flow_id"])
    assert succeeded["type"] is FlowResultType.CREATE_ENTRY


async def test_a_duplicate_unit_is_refused(hass, config_entry):
    """AC-42. Two entries for one processor would fight over the same device."""
    result = await _submit(hass, "10.0.0.9")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_a_duplicate_updates_the_stored_address(hass, config_entry):
    """Re-adding a unit that moved is a reasonable way to fix its address."""
    await _submit(hass, "10.0.0.9")
    await hass.async_block_till_done()
    assert config_entry.data["host"] == "10.0.0.9"


async def test_a_unit_without_a_serial_falls_back_to_the_host(hass):
    """AC-43. A unit that otherwise works must not be refused for lacking a serial."""
    result = await _submit(hass, "10.0.0.1", identity=_Identity(None, None))

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "host-10.0.0.1"
    assert result["title"] == "Monolith HTP-1 (10.0.0.1)"


async def test_reconfigure_updates_the_host(hass, config_entry):
    """AC-44."""
    result = await config_entry.start_reconfigure_flow(hass)
    with patch(PATCH_IDENTITY, return_value=_Identity("TESTSN0001", "Test Processor")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "10.0.0.55"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data["host"] == "10.0.0.55"


async def test_reconfigure_refuses_a_different_unit(hass, config_entry):
    """AC-44. Silently re-targeting every entity at another room would be worse than an error."""
    result = await config_entry.start_reconfigure_flow(hass)
    with patch(PATCH_IDENTITY, return_value=_Identity("TESTSN9999", "Another Processor")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "10.0.0.55"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert config_entry.data["host"] == "10.0.0.1", "the original address must be untouched"
