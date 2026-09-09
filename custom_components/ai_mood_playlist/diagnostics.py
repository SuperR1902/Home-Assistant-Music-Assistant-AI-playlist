"""Diagnostics support.

Settings -> Devices & Services -> AI Mood Playlist -> (three-dot menu on
the entry) -> Download Diagnostics gives a JSON file capturing config,
current status, discovered moods, recent log history, and a small sample
of raw library track data. Share that file for troubleshooting.

Note: genre metadata is not included in library_sample because Music
Assistant's get_library action does not expose it for any media type --
confirmed against Home Assistant's own docs and community reports, not
just this integration's own field lookups. Matching is artist/title based
for that reason; see _tracks_matching_mood() in __init__.py.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    library = store.get("library", [])
    unique_artists = {a for t in library for a in t.get("artists", [])}

    return {
        "config": dict(store.get("config", {})),
        "status": store.get("status", {}),
        "moods": store.get("moods", {}),
        "current_selections": {
            "selected_mood": store.get("selected_mood"),
            "prompt_text": store.get("prompt_text"),
            "target_player": store.get("target_player"),
            "track_count": store.get("track_count"),
            "clear_queue": store.get("clear_queue"),
        },
        "library_track_count": len(library),
        "library_unique_artists": len(unique_artists),
        "library_sample": library[:5],
        "recent_plays_tracked": len(store.get("recent_plays", [])),
        "recent_log": list(store.get("log", [])),
    }
