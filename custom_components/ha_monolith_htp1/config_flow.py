"""Adding, re-addressing and configuring one processor.

Two rules here were learned the hard way on a sibling integration and are easy to reintroduce:

1. **Every step handler takes exactly one positional argument.** Home Assistant always calls a
   step with the submitted input as the first positional parameter, so a two-parameter signature
   binds the form data to the wrong name, leaves `user_input` permanently None, and the form
   loops forever.
2. **Validation must actually read a document.** Opening a socket proves nothing: the unit
   serves its web UI on the same port, so anything that answers on 80 would pass a connect-only
   check.

Discovery is by **zeroconf**, not DHCP. The unit advertises `_htp1._tcp.local.` from firmware
2.1.2 onward; older firmware advertises nothing, so the manual step stays.

The distinction matters and it was got wrong once here. HW-03 found no MAC anywhere in the
document, which rules out `dhcp:` discovery — that needs a MAC to register a device connection.
It does **not** rule out following a unit across an address change: a moved unit re-announces
itself over mDNS, and `_abort_if_unique_id_configured(updates=...)` rewrites the stored host.
The conclusion drawn from HW-03 was about the wrong mechanism.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import (
    CONF_MAX_VOLUME_DB,
    CONF_POWER_OFF_ACTION,
    DEFAULT_POWER_OFF_ACTION,
    DOMAIN,
    POWER_OFF_ACTIONS,
)
from .htp1.client import Htp1Client, Htp1ConnectionError, Htp1Error, Htp1TimeoutError

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_HOST): TextSelector()})


def _normalise(host: str) -> str:
    """Accept what a user is likely to paste: a bare address, or a URL they copied."""
    host = host.strip().rstrip("/")
    for prefix in ("http://", "https://", "ws://", "wss://"):
        if host.lower().startswith(prefix):
            host = host[len(prefix) :]
    return host.split("/")[0].strip()


class Htp1ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add or re-address a processor."""

    VERSION = 1

    _discovered_host: str
    _discovered_identity: _Identity

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        return await self._address_step("user", user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        return await self._address_step("reconfigure", user_input)

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo):
        """A unit announced itself as `_htp1._tcp.local.`.

        The announcement is not trusted for identity. Its TXT record carries a name and a model,
        and the instance name carries a stable per-unit suffix, but the entry is keyed on the
        serial read from the unit itself so that a discovered unit and a hand-added one resolve
        to the same entry rather than to two.

        A unit that is already configured is not offered again; its stored address is corrected
        instead. That is the address self-healing this integration previously said it could not
        do, and the earlier claim was about `dhcp:` discovery rather than this.
        """
        host = discovery_info.host
        try:
            identity = await _read_identity(self.hass, host)
        except Htp1Error:
            # Something answered on the announced address but is not an HTP-1, or is not ready.
            # Silently dropping the discovery is right: the user did not ask for anything, so
            # there is nobody to show an error to.
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(identity.serial or f"host-{host}")
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._discovered_host = host
        self._discovered_identity = identity
        # Shown in the discovery card, and in the confirmation dialog's title.
        self.context["title_placeholders"] = {"name": identity.title(host)}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(self, user_input: dict[str, Any] | None = None):
        """One click, but still a click.

        Adding a processor without asking would put every room with one under Home Assistant's
        control the moment the integration is installed.
        """
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_identity.title(self._discovered_host),
                data={CONF_HOST: self._discovered_host},
            )
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={
                "name": self._discovered_identity.title(self._discovered_host),
                "host": self._discovered_host,
            },
        )

    async def _address_step(self, step_id: str, user_input: dict[str, Any] | None):
        errors: dict[str, str] = {}

        if user_input is not None:
            host = _normalise(user_input[CONF_HOST])
            if not host:
                errors["base"] = "invalid_host"
            else:
                try:
                    identity = await _read_identity(self.hass, host)
                except Htp1TimeoutError:
                    # Distinct from cannot_connect on purpose: the port answered, so the unit
                    # is probably still booting and the right advice is "wait and retry".
                    errors["base"] = "timeout_connect"
                except Htp1ConnectionError:
                    errors["base"] = "cannot_connect"
                except Htp1Error:
                    errors["base"] = "not_htp1"
                except Exception:
                    _LOGGER.exception("unexpected error probing %s", host)
                    errors["base"] = "unknown"
                else:
                    return await self._finish(step_id, host, identity)

        placeholders = None
        if step_id == "reconfigure":
            placeholders = {"host": self._get_reconfigure_entry().data[CONF_HOST]}
        return self.async_show_form(
            step_id=step_id,
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders=placeholders,
        )

    async def _finish(self, step_id: str, host: str, identity: _Identity):
        if identity.serial:
            await self.async_set_unique_id(identity.serial)
        else:
            # A unit that otherwise works must not be refused for lacking a serial. All five
            # units measured do report one, so this is a fallback rather than the norm.
            _LOGGER.warning("%s reported no serial number; keying the entry on its host", host)
            await self.async_set_unique_id(f"host-{host}")

        if step_id == "reconfigure":
            # Pointing an existing entry at a *different* processor must abort loudly rather
            # than silently re-target every entity at another room.
            self._abort_if_unique_id_mismatch(reason="wrong_device")
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data_updates={CONF_HOST: host}
            )

        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        return self.async_create_entry(title=identity.title(host), data={CONF_HOST: host})

    @staticmethod
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return Htp1OptionsFlow()


class Htp1OptionsFlow(OptionsFlow):
    """Two settings, both of which change behaviour.

    Deliberately not here: a poll interval, because there is no polling; and any "which
    entities to create" toggle, which is what the entity registry is for.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            # `async_create_entry` replaces the options dict wholesale, so a partial write would
            # silently discard whatever this form did not include.
            options = dict(self.config_entry.options)
            options.update(user_input)
            return self.async_create_entry(data=options)

        current = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POWER_OFF_ACTION,
                    default=current.get(CONF_POWER_OFF_ACTION, DEFAULT_POWER_OFF_ACTION),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(POWER_OFF_ACTIONS),
                        translation_key="power_off_action",
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_MAX_VOLUME_DB,
                    description={"suggested_value": current.get(CONF_MAX_VOLUME_DB)},
                ): NumberSelector(
                    NumberSelectorConfig(min=-100, max=20, step=1, mode=NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class _Identity:
    """What one read tells us about a unit, before an entry exists."""

    def __init__(self, serial: str | None, unit_name: str | None) -> None:
        self.serial = serial
        self.unit_name = unit_name

    def title(self, host: str) -> str:
        return self.unit_name or f"Monolith HTP-1 ({host})"


async def _read_identity(hass, host: str) -> _Identity:
    """Connect, read one document, disconnect.

    Read-only, and short-lived: the entry's own client is created later. Raises the client's
    own error types so the caller can tell "unreachable" from "answered but not an HTP-1".
    """
    client = Htp1Client(async_get_clientsession(hass), host, seed=host)
    try:
        await client.async_start()
        mirror = client.mirror
        if not mirror.loaded:
            raise Htp1Error(f"{host} did not send a document")
        return _Identity(mirror.get("serial"), mirror.get("unit_name"))
    finally:
        await client.async_stop()
