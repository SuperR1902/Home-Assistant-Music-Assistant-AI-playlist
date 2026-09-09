"""Select entities: which mood is 'up next', and which speaker to target.

Both are plain dropdowns manageable entirely from the entity's more-info
dialog or a dashboard card -- no YAML needed.
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MA_CONFIG_ENTRY,
    DOMAIN,
    NO_MOOD_OPTION,
    NO_PLAYER_OPTION,
    SIGNAL_MOODS_UPDATED,
)
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            AiMoodPlaylistMoodSelect(hass, entry),
            AiMoodPlaylistTargetPlayerSelect(hass, entry),
        ]
    )


class AiMoodPlaylistMoodSelect(SelectEntity):
    """Pick which discovered mood is 'up next' for the Play button."""

    _attr_has_entity_name = True
    _attr_name = "Mood"
    _attr_icon = "mdi:emoticon-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_mood_select"
        self._attr_device_info = device_info(entry)

    @property
    def options(self) -> list[str]:
        store = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        moods = list(store.get("moods", {}).keys())
        return moods or [NO_MOOD_OPTION]

    @property
    def current_option(self) -> str | None:
        store = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return store.get("selected_mood")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self._hass,
                f"{SIGNAL_MOODS_UPDATED}_{self._entry.entry_id}",
                self._handle_moods_updated,
            )
        )

    @callback
    def _handle_moods_updated(self) -> None:
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        if option == NO_MOOD_OPTION:
            return
        self._hass.data[DOMAIN][self._entry.entry_id]["selected_mood"] = option
        self.async_write_ha_state()


class AiMoodPlaylistTargetPlayerSelect(SelectEntity):
    """Pick which Music Assistant-backed speaker the Play button targets.

    Options are populated automatically from your Music Assistant
    integration's media_player entities -- nothing to type or configure.
    """

    _attr_has_entity_name = True
    _attr_name = "Target Speaker"
    _attr_icon = "mdi:speaker"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_target_player_select"
        self._attr_device_info = device_info(entry)

    @property
    def options(self) -> list[str]:
        store = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        ma_config_entry_id = store.get("config", {}).get(CONF_MA_CONFIG_ENTRY)
        registry = er.async_get(self._hass)
        entries = er.async_entries_for_config_entry(registry, ma_config_entry_id)
        players = sorted(e.entity_id for e in entries if e.domain == "media_player")
        return players or [NO_PLAYER_OPTION]

    @property
    def current_option(self) -> str | None:
        store = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        current = store.get("target_player")
        if current in self.options:
            return current
        return None

    async def async_select_option(self, option: str) -> None:
        if option == NO_PLAYER_OPTION:
            return
        self._hass.data[DOMAIN][self._entry.entry_id]["target_player"] = option
        self.async_write_ha_state()
