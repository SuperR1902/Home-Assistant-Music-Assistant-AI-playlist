"""Switch entity: clear the queue before playing, or add to it."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AiMoodPlaylistClearQueueSwitch(hass, entry)])


class AiMoodPlaylistClearQueueSwitch(SwitchEntity):
    """On = clear the queue before playing. Off = add to whatever's playing."""

    _attr_has_entity_name = True
    _attr_name = "Clear Queue First"
    _attr_icon = "mdi:playlist-remove"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_clear_queue_switch"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool:
        store = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return store.get("clear_queue", True)

    async def async_turn_on(self, **kwargs) -> None:
        self._hass.data[DOMAIN][self._entry.entry_id]["clear_queue"] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._hass.data[DOMAIN][self._entry.entry_id]["clear_queue"] = False
        self.async_write_ha_state()
