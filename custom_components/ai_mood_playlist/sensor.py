"""Status sensor: state + recent history as attributes.

This is the easiest way to grab troubleshooting info -- open this
entity's more-info dialog, scroll to Attributes, and copy what you see
(or use Settings -> Devices & Services -> AI Mood Playlist -> Download
Diagnostics for the full machine-readable version).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MAX_LOG_IN_SENSOR, SIGNAL_MOODS_UPDATED, SIGNAL_STATUS_UPDATED
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AiMoodPlaylistStatusSensor(hass, entry)])


class AiMoodPlaylistStatusSensor(SensorEntity):
    """State is idle/running/ok/error. Attributes carry the useful detail."""

    _attr_has_entity_name = True
    _attr_name = "Status"
    _attr_icon = "mdi:text-box-check-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_status_sensor"
        self._attr_device_info = device_info(entry)

    @property
    def _store(self) -> dict:
        return self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})

    @property
    def native_value(self) -> str:
        return self._store.get("status", {}).get("state", "idle")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        store = self._store
        status = store.get("status", {})
        recent_log = list(store.get("log", []))[-MAX_LOG_IN_SENSOR:]
        return {
            "last_action": status.get("last_action"),
            "last_message": status.get("last_message"),
            "last_run_at": status.get("last_run_at"),
            "library_track_count": status.get("library_track_count", 0),
            "mood_count": status.get("mood_count", 0),
            "moods": list(store.get("moods", {}).keys()),
            "now_playing_source": status.get("now_playing_source"),
            "now_playing_value": status.get("now_playing_value"),
            "now_playing_speaker": status.get("now_playing_speaker"),
            "now_playing_since": status.get("now_playing_since"),
            "recent_plays_tracked": len(store.get("recent_plays", [])),
            "recent_log": [
                f"[{e['time']}] {e['level'].upper()} {e['action']}: {e['message']}"
                for e in recent_log
            ],
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self._hass,
                f"{SIGNAL_STATUS_UPDATED}_{self._entry.entry_id}",
                self._handle_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self._hass,
                f"{SIGNAL_MOODS_UPDATED}_{self._entry.entry_id}",
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
