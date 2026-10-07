"""UI setup for a single explicitly selected amplifier."""

from ipaddress import IPv4Address

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from . import DOMAIN


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors = {}
        if user_input is not None:
            try:
                address = IPv4Address(user_input["host"].strip())
                if address.is_unspecified or address.is_multicast or address == IPv4Address("255.255.255.255"):
                    raise ValueError("Not a unicast address")
            except ValueError:
                errors["host"] = "invalid_host"
            else:
                host = str(address)
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Devialet Expert", data={"host": host})
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("host"): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    "read_only", default=self.config_entry.options.get("read_only", True)
                ): bool,
            }),
        )
