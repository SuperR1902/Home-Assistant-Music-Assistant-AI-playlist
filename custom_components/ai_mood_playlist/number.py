"""Number entity for how many tracks to queue."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_TRACK_COUNT, DOMAIN
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AiMoodPlaylistTrackCountNumber(hass, entry)])


class AiMoodPlaylistTrackCountNumber(NumberEntity):
    """How many tracks the Play button queues."""

    _attr_has_entity_name = True
    _attr_name = "Track Count"
    _attr_icon = "mdi:counter"
    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_track_count_number"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> float:
        store = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return store.get("track_count", DEFAULT_TRACK_COUNT)

    async def async_set_native_value(self, value: float) -> None:
        self._hass.data[DOMAIN][self._entry.entry_id]["track_count"] = int(value)
        self.async_write_ha_state()
