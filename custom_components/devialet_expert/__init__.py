"""Devialet Expert integration; passive by default."""

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType

from .client import Client

DOMAIN = "devialet_expert"
PLATFORMS = [Platform.MEDIA_PLAYER, Platform.NUMBER]
ARTWORK_URL = "/devialet_expert/expert.png"
OFF_ARTWORK_URL = "/devialet_expert/expert-off.png"
BOOT_ARTWORK_URL = "/devialet_expert/expert-boot.png"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    await hass.http.async_register_static_paths([
        StaticPathConfig(url, str(Path(__file__).parent / "brand" / name), True)
        for url, name in (
            (ARTWORK_URL, "expert.png"),
            (OFF_ARTWORK_URL, "expert-off.png"),
            (BOOT_ARTWORK_URL, "expert-boot.png"),
        )
    ])
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    def changed() -> None:
        from homeassistant.helpers.dispatcher import async_dispatcher_send

        async_dispatcher_send(hass, f"{DOMAIN}_{entry.entry_id}")

    client = Client(
        entry.data["host"], entry.options.get("read_only", True), changed
    )
    try:
        await client.start()
    except (OSError, TimeoutError) as err:
        client.close()
        raise ConfigEntryNotReady(
            f"No Devialet status on UDP 45454 from {entry.data['host']}: {err}"
        ) from err
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = client
    entry.async_on_unload(hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP, lambda event: client.close()
    ))
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    forwarded = False
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        forwarded = True
    finally:
        if not forwarded:
            client.close()
            hass.data[DOMAIN].pop(entry.entry_id, None)
    return True


async def _options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id).close()
        return True
    return False
