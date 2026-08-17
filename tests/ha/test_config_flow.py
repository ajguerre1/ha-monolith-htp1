"""Adding and re-addressing a processor.

The flow is the only part of this integration most users will ever consciously interact with,
and they will do it once, while something is not working. So the tests care as much about *which*
error is reported as about whether one is: "could not reach that address" and "it answered but
did not complete the connection" call for different actions from the person reading them.
"""

from __future__ import annotations

from ipaddress import ip_address
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

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
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
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


def _discovery(host: str = "10.0.0.1", name: str = "Test Processor") -> ZeroconfServiceInfo:
    """What the unit actually announces, copied from a live capture.

    Firmware 2.1.2 added the advertisement; the instance name carries a stable per-unit suffix
    that appears nowhere in the MSO document.
    """
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        port=80,
        hostname=f"{name.replace(' ', '-')}-332c15.local.",
        type="_htp1._tcp.local.",
        name=f"{name.replace(' ', '-')}-332c15._htp1._tcp.local.",
        properties={"model": "HTP-1", "name": name, "swVer": "V2.1.2"},
    )


async def test_a_discovered_processor_is_offered_not_added(hass):
    """Discovery must ask. Adding on sight would put every room under control on install."""
    with patch(PATCH_IDENTITY, return_value=_Identity("TESTSN0001", "Test Processor")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_discovery()
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"


async def test_confirming_a_discovery_creates_the_entry(hass):
    with patch(PATCH_IDENTITY, return_value=_Identity("TESTSN0001", "Test Processor")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_discovery()
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"host": "10.0.0.1"}
    assert result["result"].unique_id == "TESTSN0001"


async def test_identity_comes_from_the_unit_not_the_announcement(hass):
    """The TXT record is not trusted for identity.

    A discovered unit and a hand-added one must resolve to the same entry, so both key on the
    serial read from the device itself rather than on anything in the announcement.
    """
    with patch(PATCH_IDENTITY, return_value=_Identity("REALSERIAL", "Real Name")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_ZEROCONF},
            data=_discovery(name="Whatever mDNS Says"),
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["result"].unique_id == "REALSERIAL"
    assert result["title"] == "Real Name"


async def test_a_moved_unit_has_its_address_corrected(hass, config_entry):
    """The self-heal this integration once said it could not do.

    HW-03 found no MAC in the document, which does rule out `dhcp:` discovery. The conclusion
    drawn from it — that Home Assistant could never follow a unit across an address change — was
    about the wrong mechanism. The unit re-announces itself at its new address, and the entry is
    updated rather than duplicated.
    """
    assert config_entry.data["host"] == "10.0.0.1"

    with patch(PATCH_IDENTITY, return_value=_Identity("TESTSN0001", "Test Processor")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_discovery("10.0.0.77")
        )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data["host"] == "10.0.0.77", "the stored address should have moved"


async def test_an_announcement_from_something_else_is_dropped_quietly(hass):
    """Nobody asked for this, so there is nobody to show an error to."""
    with patch(PATCH_IDENTITY, side_effect=Htp1Error("not an HTP-1")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_discovery()
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
