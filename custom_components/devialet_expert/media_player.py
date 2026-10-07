"""A status-backed amplifier, not a playback source."""

from homeassistant.components.media_player import (
    MediaPlayerEntity, MediaPlayerEntityFeature, MediaPlayerState,
)
from homeassistant.components.media_player.const import MediaPlayerDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN
from .client import Client, CommandError
from .protocol import MAX_DB, MIN_DB, STEP_DB, db_to_level, level_to_db


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([DevialetPlayer(hass.data[DOMAIN][entry.entry_id], entry)])


class DevialetPlayer(MediaPlayerEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER

    def __init__(self, client: Client, entry: ConfigEntry) -> None:
        self.client = client
        self.entry = entry
        self._attr_unique_id = entry.data["host"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data["host"])},
            name=client.status.name if client.status else "Devialet Expert",
            manufacturer="Devialet",
            model="Expert (experimental UDP)",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, f"{DOMAIN}_{self.entry.entry_id}", self.async_write_ha_state
        ))

    @property
    def available(self):
        return self.client.available

    @property
    def supported_features(self):
        if self.client.read_only:
            return MediaPlayerEntityFeature(0)
        return (
            MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.VOLUME_MUTE | MediaPlayerEntityFeature.SELECT_SOURCE
        )

    @property
    def state(self):
        status = self.client.status
        return MediaPlayerState.ON if status and status.power else MediaPlayerState.OFF

    @property
    def volume_level(self):
        return db_to_level(self.client.status.volume_db) if self.client.status else None

    @property
    def is_volume_muted(self):
        return self.client.status.muted if self.client.status else None

    @property
    def source(self):
        return self.client.status.source if self.client.status else None

    @property
    def source_list(self):
        return [name for _, name in self.client.status.inputs] if self.client.status else []

    @property
    def extra_state_attributes(self):
        return {
            "volume_db": self.client.status.volume_db if self.client.status else None,
            "active_input": self.client.status.source if self.client.status else None,
            "muted": self.client.status.muted if self.client.status else None,
            "volume_min_db": MIN_DB,
            "volume_max_db": MAX_DB,
            "read_only": self.client.read_only,
            "host": self.client.host,
        }

    async def _command(self, kind, value):
        try:
            await self.client.command(kind, value)
        except (CommandError, TimeoutError) as err:
            message = str(err) or "No confirming Devialet status within five seconds"
            raise HomeAssistantError(message) from err

    async def async_set_volume_level(self, volume):
        try:
            db = level_to_db(volume)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await self._command("volume", db)

    async def async_volume_up(self):
        await self._command("step", STEP_DB)

    async def async_volume_down(self):
        await self._command("step", -STEP_DB)

    async def async_mute_volume(self, mute):
        await self._command("mute", mute)

    async def async_turn_on(self):
        await self._command("power", True)

    async def async_turn_off(self):
        await self._command("power", False)

    async def async_select_source(self, source):
        status = self.client.status
        if status:
            for index, name in status.inputs:
                if source == name:
                    await self._command("source", index)
                    return
        raise HomeAssistantError(f"Unknown Devialet input: {source}")
