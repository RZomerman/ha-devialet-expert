"""Native decibel volume control for the amplifier."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN
from .client import Client, CommandError
from .protocol import MAX_DB, MIN_DB, STEP_DB


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([DevialetVolume(hass.data[DOMAIN][entry.entry_id], entry)])


class DevialetVolume(NumberEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Volume"
    _attr_icon = "mdi:volume-high"
    _attr_native_unit_of_measurement = "dB"
    _attr_native_min_value = MIN_DB
    _attr_native_max_value = MAX_DB
    _attr_native_step = STEP_DB
    _attr_mode = NumberMode.SLIDER

    def __init__(self, client: Client, entry: ConfigEntry) -> None:
        self.client = client
        self.entry = entry
        self._attr_unique_id = f"{entry.data['host']}_volume_db"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data["host"])}
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, f"{DOMAIN}_{self.entry.entry_id}", self.async_write_ha_state
        ))

    @property
    def available(self) -> bool:
        return (
            self.client.available and not self.client.read_only
            and not self.client.powering_up
        )

    @property
    def native_value(self) -> float | None:
        return self.client.status.volume_db if self.client.status else None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.client.command("volume", value)
        except (CommandError, TimeoutError) as err:
            message = str(err) or "No confirming Devialet status within five seconds"
            raise HomeAssistantError(message) from err
