"""Text entity for the free-text playlist prompt."""
from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AiMoodPlaylistPromptText(hass, entry)])


class AiMoodPlaylistPromptText(TextEntity):
    """Free-text request, e.g. 'moody 90s trip-hop for a rainy evening'.

    If this is non-empty when Play is pressed, it's used instead of the
    Mood dropdown. Clear it to go back to mood-based playback.
    """

    _attr_has_entity_name = True
    _attr_name = "Prompt"
    _attr_icon = "mdi:text-box-outline"
    _attr_mode = TextMode.TEXT
    _attr_native_max = 200

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_prompt_text"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> str:
        store = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return store.get("prompt_text", "")

    async def async_set_value(self, value: str) -> None:
        self._hass.data[DOMAIN][self._entry.entry_id]["prompt_text"] = value
        self.async_write_ha_state()
