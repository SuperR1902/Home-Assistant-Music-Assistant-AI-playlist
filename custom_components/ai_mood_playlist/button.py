"""Buttons that trigger the integration's actions from the GUI.

Play reads the other entities (Mood select, Target Speaker select, Prompt
text, Track Count number, Clear Queue First switch) and decides whether to
use the free-text prompt or the selected mood, mirroring the ha-ai-playlist
"prompt overrides playlist if present" convention.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import (
    DEFAULT_MOOD_COUNT_MAX,
    DEFAULT_MOOD_COUNT_MIN,
    async_discover_moods,
    async_play_mood,
    async_play_prompt,
    async_refresh_library,
)
from .const import DOMAIN
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            AiMoodPlaylistPlayButton(hass, entry),
            AiMoodPlaylistRefreshButton(hass, entry),
            AiMoodPlaylistDiscoverButton(hass, entry),
        ]
    )


class _BaseButton(ButtonEntity):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, name: str, icon: str) -> None:
        self._hass = hass
        self._entry = entry
        self._attr_has_entity_name = True
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{name.lower().replace(' ', '_')}_button"
        self._attr_device_info = device_info(entry)

    @property
    def _store(self) -> dict:
        return self._hass.data[DOMAIN][self._entry.entry_id]


class AiMoodPlaylistPlayButton(_BaseButton):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, "Play", "mdi:play-circle")

    async def async_press(self) -> None:
        store = self._store
        target_player = store.get("target_player")
        prompt_text = (store.get("prompt_text") or "").strip()
        track_count = int(store.get("track_count", 15))
        clear_queue = bool(store.get("clear_queue", True))

        # Target-speaker validation happens inside async_play_mood/
        # async_play_prompt so it's captured by the status sensor + log the
        # same way any other failure is, regardless of how Play was invoked.
        if prompt_text:
            await async_play_prompt(
                self._hass,
                self._entry.entry_id,
                prompt_text,
                target_player,
                track_count,
                clear_queue,
            )
        else:
            mood_name = store.get("selected_mood")
            await async_play_mood(
                self._hass,
                self._entry.entry_id,
                mood_name,
                target_player,
                track_count,
                clear_queue,
            )


class AiMoodPlaylistRefreshButton(_BaseButton):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, "Refresh Library Now", "mdi:refresh")

    async def async_press(self) -> None:
        await async_refresh_library(self._hass, self._entry.entry_id)


class AiMoodPlaylistDiscoverButton(_BaseButton):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, "Discover Moods Now", "mdi:auto-fix")

    async def async_press(self) -> None:
        await async_discover_moods(
            self._hass,
            self._entry.entry_id,
            DEFAULT_MOOD_COUNT_MIN,
            DEFAULT_MOOD_COUNT_MAX,
        )
