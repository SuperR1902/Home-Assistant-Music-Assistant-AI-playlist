"""AI Mood Playlist integration.

Reads your Music Assistant library, asks an AI Task entity to propose
mood categories (or interpret a free-text prompt) based on what's
actually in your library, then builds playlists by filtering your real,
already-owned tracks -- so every track it queues is guaranteed playable.

Every action records its outcome to an in-memory status/log that backs
the "AI Mood Playlist Status" sensor and this entry's Diagnostics download,
so troubleshooting doesn't require digging through the main HA log.
"""
from __future__ import annotations

import json
import logging
import random
import re
from collections import Counter, deque
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AI_TASK_ENTITY,
    CONF_AUTO_DISCOVER_AFTER_REFRESH,
    CONF_MA_CONFIG_ENTRY,
    CONF_REFRESH_INTERVAL_HOURS,
    DEFAULT_AUTO_DISCOVER_AFTER_REFRESH,
    DEFAULT_MOOD_COUNT_MAX,
    DEFAULT_MOOD_COUNT_MIN,
    DEFAULT_REFRESH_INTERVAL_HOURS,
    DEFAULT_TRACK_COUNT,
    DOMAIN,
    GENERIC_ARTIST_MARKERS,
    LIBRARY_PAGE_SIZE,
    MAX_ARTIST_HINTS_PER_MOOD,
    MAX_ARTISTS_IN_SUMMARY,
    MAX_COMPILATION_ALBUMS_LISTED,
    MAX_LOG_ENTRIES,
    MAX_RECENT_PLAYS,
    MOOD_SAMPLE_SIZE,
    NO_PLAYER_OPTION,
    SIGNAL_MOODS_UPDATED,
    SIGNAL_STATUS_UPDATED,
    STATE_ERROR,
    STATE_IDLE,
    STATE_OK,
    STATE_RUNNING,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

PLATFORMS = ["select", "text", "number", "switch", "button", "sensor"]

SERVICE_REFRESH_LIBRARY = "refresh_library"
SERVICE_DISCOVER_MOODS = "discover_moods"
SERVICE_PLAY_MOOD = "play_mood"
SERVICE_PLAY_PROMPT = "play_prompt"

REFRESH_LIBRARY_SCHEMA = vol.Schema({vol.Optional("entry_id"): cv.string})

DISCOVER_MOODS_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
        vol.Optional("mood_count_min", default=DEFAULT_MOOD_COUNT_MIN): cv.positive_int,
        vol.Optional("mood_count_max", default=DEFAULT_MOOD_COUNT_MAX): cv.positive_int,
    }
)

PLAY_MOOD_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("mood"): cv.string,
        vol.Optional("track_count", default=DEFAULT_TRACK_COUNT): cv.positive_int,
        vol.Optional("clear_queue", default=True): cv.boolean,
        vol.Optional("entry_id"): cv.string,
    }
)

PLAY_PROMPT_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("prompt"): cv.string,
        vol.Optional("track_count", default=DEFAULT_TRACK_COUNT): cv.positive_int,
        vol.Optional("clear_queue", default=True): cv.boolean,
        vol.Optional("entry_id"): cv.string,
    }
)


def _new_store(entry: ConfigEntry) -> dict[str, Any]:
    return {
        "config": entry.data,
        "library": [],
        "moods": {},
        "selected_mood": None,
        "prompt_text": "",
        "track_count": DEFAULT_TRACK_COUNT,
        "clear_queue": True,
        "target_player": None,
        "recent_plays": deque(maxlen=MAX_RECENT_PLAYS),
        "status": {
            "state": STATE_IDLE,
            "last_action": None,
            "last_message": "Not run yet.",
            "last_run_at": None,
            "library_track_count": 0,
            "mood_count": 0,
            "now_playing_source": None,
            "now_playing_value": None,
            "now_playing_speaker": None,
            "now_playing_since": None,
        },
        "log": deque(maxlen=MAX_LOG_ENTRIES),
    }


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AI Mood Playlist from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    store = _new_store(entry)

    storage = Store[dict[str, Any]](hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")
    store["_storage"] = storage
    try:
        persisted = await storage.async_load()
    except Exception as err:  # noqa: BLE001 -- a corrupt cache file shouldn't block setup
        _LOGGER.warning("Could not load persisted AI Mood Playlist data: %s", err)
        persisted = None
    if persisted:
        store["library"] = persisted.get("library", [])
        store["moods"] = persisted.get("moods", {})
        store["recent_plays"] = deque(
            persisted.get("recent_plays", []), maxlen=MAX_RECENT_PLAYS
        )
        if store["library"] or store["moods"]:
            store["status"]["last_message"] = (
                f"Restored {len(store['library'])} cached tracks and "
                f"{len(store['moods'])} moods from disk."
            )
            store["status"]["library_track_count"] = len(store["library"])
            store["status"]["mood_count"] = len(store["moods"])

    hass.data[DOMAIN][entry.entry_id] = store

    _register_services(hass)
    _setup_periodic_refresh(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_persist(hass: HomeAssistant, entry_id: str) -> None:
    """Save the library cache, discovered moods, and recent-plays history
    so they survive restarts."""
    store = hass.data[DOMAIN][entry_id]
    try:
        await store["_storage"].async_save(
            {
                "library": store["library"],
                "moods": store["moods"],
                "recent_plays": list(store["recent_plays"]),
            }
        )
    except Exception as err:  # noqa: BLE001 -- persistence failing shouldn't fail the action
        _LOGGER.warning("Could not persist AI Mood Playlist data: %s", err)


def _setup_periodic_refresh(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register a timer that periodically re-indexes the library."""
    interval_hours = entry.data.get(
        CONF_REFRESH_INTERVAL_HOURS, DEFAULT_REFRESH_INTERVAL_HOURS
    )
    if not interval_hours:
        return

    auto_discover = entry.data.get(
        CONF_AUTO_DISCOVER_AFTER_REFRESH, DEFAULT_AUTO_DISCOVER_AFTER_REFRESH
    )

    async def _periodic_refresh(_now) -> None:
        try:
            await async_refresh_library(hass, entry.entry_id)
            if auto_discover:
                await async_discover_moods(
                    hass, entry.entry_id, DEFAULT_MOOD_COUNT_MIN, DEFAULT_MOOD_COUNT_MAX
                )
        except HomeAssistantError:
            # Already written to the status sensor + log by the functions
            # above -- swallow here so the scheduler doesn't also dump a
            # duplicate traceback into the core log.
            pass

    remove = async_track_time_interval(
        hass, _periodic_refresh, timedelta(hours=interval_hours)
    )
    entry.async_on_unload(remove)


# ---------------------------------------------------------------------------
# Status / log tracking (backs the sensor + diagnostics download)
# ---------------------------------------------------------------------------

def _record(
    hass: HomeAssistant, entry_id: str, level: str, action: str, message: str
) -> None:
    """Log an event to this entry's in-memory history and update its status."""
    store = hass.data[DOMAIN][entry_id]
    now = dt_util.utcnow()
    store["log"].append(
        {"time": now.isoformat(), "level": level, "action": action, "message": message}
    )
    store["status"]["last_action"] = action
    store["status"]["last_message"] = message
    store["status"]["last_run_at"] = now.isoformat()
    store["status"]["state"] = STATE_ERROR if level == "error" else STATE_OK
    store["status"]["library_track_count"] = len(store["library"])
    store["status"]["mood_count"] = len(store["moods"])

    log_fn = _LOGGER.error if level == "error" else _LOGGER.info
    log_fn("AI Mood Playlist [%s]: %s", action, message)

    async_dispatcher_send(hass, f"{SIGNAL_STATUS_UPDATED}_{entry_id}")


def _mark_running(hass: HomeAssistant, entry_id: str, action: str) -> None:
    store = hass.data[DOMAIN][entry_id]
    store["status"]["state"] = STATE_RUNNING
    store["status"]["last_action"] = action
    async_dispatcher_send(hass, f"{SIGNAL_STATUS_UPDATED}_{entry_id}")


async def _notify(hass: HomeAssistant, title: str, message: str, notification_id: str) -> None:
    """Show a dismissible HA notification. Best-effort -- a notification
    failing to display shouldn't fail whatever action triggered it."""
    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"AI Mood Playlist: {title}",
                "message": message,
                "notification_id": f"{DOMAIN}_{notification_id}",
            },
            blocking=True,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not create notification: %s", err)


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH_LIBRARY):
        return  # services are global, only register once

    async def handle_refresh_library(call: ServiceCall) -> None:
        entry_id, _ = _resolve_entry(hass, call.data.get("entry_id"))
        await async_refresh_library(hass, entry_id)

    async def handle_discover_moods(call: ServiceCall) -> None:
        entry_id, _ = _resolve_entry(hass, call.data.get("entry_id"))
        await async_discover_moods(
            hass,
            entry_id,
            call.data.get("mood_count_min", DEFAULT_MOOD_COUNT_MIN),
            call.data.get("mood_count_max", DEFAULT_MOOD_COUNT_MAX),
        )

    async def handle_play_mood(call: ServiceCall) -> None:
        entry_id, store = _resolve_entry(hass, call.data.get("entry_id"))
        mood_name = call.data.get("mood") or store.get("selected_mood")
        await async_play_mood(
            hass,
            entry_id,
            mood_name,
            call.data["entity_id"],
            call.data.get("track_count", DEFAULT_TRACK_COUNT),
            call.data.get("clear_queue", True),
        )

    async def handle_play_prompt(call: ServiceCall) -> None:
        entry_id, _ = _resolve_entry(hass, call.data.get("entry_id"))
        await async_play_prompt(
            hass,
            entry_id,
            call.data["prompt"],
            call.data["entity_id"],
            call.data.get("track_count", DEFAULT_TRACK_COUNT),
            call.data.get("clear_queue", True),
        )

    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH_LIBRARY, handle_refresh_library, schema=REFRESH_LIBRARY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISCOVER_MOODS, handle_discover_moods, schema=DISCOVER_MOODS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PLAY_MOOD, handle_play_mood, schema=PLAY_MOOD_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PLAY_PROMPT, handle_play_prompt, schema=PLAY_PROMPT_SCHEMA
    )


def _resolve_entry(hass: HomeAssistant, entry_id: str | None) -> tuple[str, dict[str, Any]]:
    store = hass.data.get(DOMAIN, {})
    if entry_id:
        if entry_id not in store:
            raise HomeAssistantError(f"Unknown AI Mood Playlist entry_id '{entry_id}'")
        return entry_id, store[entry_id]
    if len(store) == 1:
        ((only_id, only_store),) = store.items()
        return only_id, only_store
    raise HomeAssistantError(
        "Multiple AI Mood Playlist entries configured; pass 'entry_id' to disambiguate."
    )


# ---------------------------------------------------------------------------
# Core actions -- called by services, buttons, and the periodic timer alike
# ---------------------------------------------------------------------------

async def async_refresh_library(hass: HomeAssistant, entry_id: str) -> None:
    _mark_running(hass, entry_id, "refresh_library")
    store = hass.data[DOMAIN][entry_id]
    try:
        ma_config_entry_id = store["config"][CONF_MA_CONFIG_ENTRY]
        tracks = await _fetch_library(hass, ma_config_entry_id)
        store["library"] = tracks
        unique_artists = len({a for t in tracks for a in t["artists"]})
        await _async_persist(hass, entry_id)
        _record(
            hass,
            entry_id,
            "info",
            "refresh_library",
            f"Cached {len(tracks)} tracks across {unique_artists} artists.",
        )
    except Exception as err:  # noqa: BLE001 -- surface any failure to the status sensor
        _record(hass, entry_id, "error", "refresh_library", f"Failed: {err}")
        raise HomeAssistantError(f"AI Mood Playlist library refresh failed: {err}") from err


async def async_discover_moods(
    hass: HomeAssistant, entry_id: str, mood_count_min: int, mood_count_max: int
) -> None:
    _mark_running(hass, entry_id, "discover_moods")
    store = hass.data[DOMAIN][entry_id]
    try:
        if not store["library"]:
            raise HomeAssistantError(
                "Library cache is empty. Press 'Refresh Library Now' first."
            )
        ai_task_entity_id = store["config"][CONF_AI_TASK_ENTITY]
        moods, raw_text = await _discover_moods(
            hass, store["library"], ai_task_entity_id, mood_count_min, mood_count_max
        )
        store["moods"] = moods
        async_dispatcher_send(hass, f"{SIGNAL_MOODS_UPDATED}_{entry_id}")
        if moods:
            await _async_persist(hass, entry_id)
            _record(
                hass,
                entry_id,
                "info",
                "discover_moods",
                f"Discovered {len(moods)} moods: {', '.join(moods.keys())}",
            )
            await _notify(
                hass,
                f"Discovered {len(moods)} moods",
                ", ".join(moods.keys()),
                "moods_discovered",
            )
        else:
            _record(
                hass,
                entry_id,
                "error",
                "discover_moods",
                "AI response could not be parsed as mood JSON. "
                f"Raw response (truncated): {raw_text[:300]!r}",
            )
    except HomeAssistantError as err:
        _record(hass, entry_id, "error", "discover_moods", str(err))
        raise
    except Exception as err:  # noqa: BLE001
        _record(hass, entry_id, "error", "discover_moods", f"Failed: {err}")
        raise HomeAssistantError(f"AI Mood Playlist mood discovery failed: {err}") from err


async def async_play_mood(
    hass: HomeAssistant,
    entry_id: str,
    mood_name: str | None,
    entity_id: str | None,
    track_count: int,
    clear_queue: bool,
) -> None:
    _mark_running(hass, entry_id, "play_mood")
    store = hass.data[DOMAIN][entry_id]
    try:
        _require_target_player(entity_id)
        if not mood_name:
            raise HomeAssistantError(
                "No mood specified and no mood currently selected."
            )
        mood = store["moods"].get(mood_name)
        if mood is None:
            raise HomeAssistantError(
                f"Unknown mood '{mood_name}'. Available: {list(store['moods'].keys())}"
            )
        chosen, stage = await _do_play(
            hass, entry_id, mood, entity_id, track_count, clear_queue
        )
        _set_now_playing(hass, entry_id, "mood", mood_name, entity_id)
        unique_artists = len({a for t in chosen for a in t["artists"]})
        _record(
            hass,
            entry_id,
            "info",
            "play_mood",
            f"Queued {len(chosen)} tracks across {unique_artists} artists for "
            f"mood '{mood_name}' on {entity_id}.{_stage_note(stage)}",
        )
    except HomeAssistantError as err:
        _record(hass, entry_id, "error", "play_mood", str(err))
        raise
    except Exception as err:  # noqa: BLE001
        _record(hass, entry_id, "error", "play_mood", f"Failed: {err}")
        raise HomeAssistantError(f"AI Mood Playlist play_mood failed: {err}") from err


async def async_play_prompt(
    hass: HomeAssistant,
    entry_id: str,
    prompt: str,
    entity_id: str | None,
    track_count: int,
    clear_queue: bool,
) -> None:
    _mark_running(hass, entry_id, "play_prompt")
    store = hass.data[DOMAIN][entry_id]
    try:
        _require_target_player(entity_id)
        if not store["library"]:
            raise HomeAssistantError(
                "Library cache is empty. Press 'Refresh Library Now' first."
            )
        ai_task_entity_id = store["config"][CONF_AI_TASK_ENTITY]
        mood, raw_text = await _interpret_prompt(
            hass, store["library"], ai_task_entity_id, prompt
        )
        parse_failed = not mood.get("artist_hints") and not mood.get("title_keywords")
        if parse_failed:
            _record(
                hass,
                entry_id,
                "error",
                "play_prompt",
                "Could not extract artist/title matches from the AI's response "
                f"to prompt {prompt!r}. Raw response (truncated): {raw_text[:300]!r}",
            )
        chosen, stage = await _do_play(
            hass, entry_id, mood, entity_id, track_count, clear_queue
        )
        _set_now_playing(hass, entry_id, "prompt", prompt, entity_id)
        unique_artists = len({a for t in chosen for a in t["artists"]})
        _record(
            hass,
            entry_id,
            "info",
            "play_prompt",
            f"Prompt {prompt!r} -> queued {len(chosen)} tracks across "
            f"{unique_artists} artists on {entity_id}.{_stage_note(stage)}",
        )
    except HomeAssistantError as err:
        _record(hass, entry_id, "error", "play_prompt", str(err))
        raise
    except Exception as err:  # noqa: BLE001
        _record(hass, entry_id, "error", "play_prompt", f"Failed: {err}")
        raise HomeAssistantError(f"AI Mood Playlist play_prompt failed: {err}") from err


def _stage_note(stage: str) -> str:
    """Human-readable caveat for how a match was found, appended to log
    messages so a degraded match is visible without digging into details."""
    if stage == "secondary":
        return (
            " (the declared match type found nothing -- used the other "
            "signal, artist or title, as a fallback before giving up)"
        )
    if stage == "none":
        return " (no artist/title matches at all -- used a random library sample instead)"
    return ""


def _set_now_playing(
    hass: HomeAssistant, entry_id: str, source: str, value: str, entity_id: str
) -> None:
    store = hass.data[DOMAIN][entry_id]
    store["status"]["now_playing_source"] = source
    store["status"]["now_playing_value"] = value
    store["status"]["now_playing_speaker"] = entity_id
    store["status"]["now_playing_since"] = dt_util.utcnow().isoformat()


def _require_target_player(entity_id: str | None) -> None:
    if not entity_id or entity_id == NO_PLAYER_OPTION:
        raise HomeAssistantError(
            "No target speaker selected. Choose one from the 'Target Speaker' "
            "dropdown, or pass 'entity_id' explicitly."
        )


async def _do_play(
    hass: HomeAssistant,
    entry_id: str,
    mood: dict[str, Any],
    entity_id: str,
    track_count: int,
    clear_queue: bool,
) -> tuple[list[dict[str, Any]], str]:
    """Queue tracks matching mood. Returns (tracks_queued, stage) where
    stage is "primary" (declared match_mode found results), "secondary"
    (fell back to the other signal), or "none" (matched nothing at all,
    used a random sample of the whole library)."""
    store = hass.data[DOMAIN][entry_id]
    if not store["library"]:
        raise HomeAssistantError(
            "Library cache is empty. Press 'Refresh Library Now' first."
        )

    candidates, stage = _tracks_matching_mood_staged(store["library"], mood)
    if stage == "none":
        candidates = [
            {**track, "_title_hit": False, "_artist_hit": False}
            for track in store["library"]
        ]

    avoid_uris = set(store["recent_plays"])
    chosen = _select_tracks(candidates, track_count, avoid_uris=avoid_uris)

    for i, track in enumerate(chosen):
        enqueue_mode = "replace" if (i == 0 and clear_queue) else "add"
        await hass.services.async_call(
            "music_assistant",
            "play_media",
            {
                "entity_id": entity_id,
                "media_id": track["uri"],
                "media_type": "track",
                "enqueue": enqueue_mode,
            },
            blocking=True,
        )

    store["recent_plays"].extend(t["uri"] for t in chosen)
    await _async_persist(hass, entry_id)

    return chosen, stage


def _select_tracks(
    candidates: list[dict[str, Any]],
    track_count: int,
    avoid_uris: frozenset[str] | set[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Pick track_count tracks from candidates, favoring higher-confidence
    matches, spreading across artists, and avoiding recent repeats.

    Tracks not in avoid_uris (not recently played) are drawn from first;
    avoid_uris tracks only fill in if there aren't enough fresh ones to
    reach track_count, so repetition is minimized without ever leaving a
    small, niche-matching mood with nothing to play at all. Within each of
    those tiers, a literal title-keyword hit is stronger evidence of fit
    than "this track is by an artist we hinted at" (which pulls in an
    artist's whole catalog under match_mode "artist"/"both"), so
    title-confirmed tracks are filled first there too.
    """

    def _tiered(pool: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
        title_hits = [t for t in pool if t.get("_title_hit")]
        others = [t for t in pool if not t.get("_title_hit")]
        picked = _diverse_sample(title_hits, count)
        if len(picked) < count:
            picked += _diverse_sample(others, count - len(picked))
        return picked

    fresh = [c for c in candidates if c["uri"] not in avoid_uris]
    recent = [c for c in candidates if c["uri"] in avoid_uris]

    selected = _tiered(fresh, track_count)
    if len(selected) < track_count:
        selected += _tiered(recent, track_count - len(selected))
    return selected


def _diverse_sample(
    candidates: list[dict[str, Any]], track_count: int
) -> list[dict[str, Any]]:
    """Round-robin across artists so a mood/prompt matching several artists
    doesn't end up dominated by whichever one has the biggest catalog."""
    if track_count <= 0 or not candidates:
        return []

    by_artist: dict[str, list[dict[str, Any]]] = {}
    for track in candidates:
        key = track["artists"][0] if track["artists"] else "Unknown"
        by_artist.setdefault(key, []).append(track)
    for tracks in by_artist.values():
        random.shuffle(tracks)

    artist_keys = list(by_artist.keys())
    random.shuffle(artist_keys)

    selected: list[dict[str, Any]] = []
    idx = 0
    while len(selected) < track_count and any(by_artist[k] for k in artist_keys):
        key = artist_keys[idx % len(artist_keys)]
        if by_artist[key]:
            selected.append(by_artist[key].pop())
        idx += 1
    return selected


# ---------------------------------------------------------------------------
# Music Assistant library access
# ---------------------------------------------------------------------------

async def _fetch_library(hass: HomeAssistant, ma_config_entry_id: str) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = await hass.services.async_call(
            "music_assistant",
            "get_library",
            {
                "config_entry_id": ma_config_entry_id,
                "media_type": "track",
                "limit": LIBRARY_PAGE_SIZE,
                "offset": offset,
            },
            blocking=True,
            return_response=True,
        )
        items = (response or {}).get("items", [])
        if not items:
            break
        for item in items:
            tracks.append(_normalize_track(item))
        if len(items) < LIBRARY_PAGE_SIZE:
            break
        offset += LIBRARY_PAGE_SIZE
    return tracks


def _normalize_track(item: dict[str, Any]) -> dict[str, Any]:
    """Pull out the fields we care about.

    CONFIRMED (not just suspected): Home Assistant's music_assistant.get_library
    action returns a deliberately lean summary for each item -- name, uri,
    artists, album -- and does NOT include genre metadata for any media
    type, regardless of how well-tagged your files are. This isn't a
    field-name mismatch to fix; genre data is simply not exposed by this
    action. Matching therefore relies on artist names (which the AI is
    expected to map to moods using its own knowledge of those artists) and
    on keywords found in track/album titles, not on genre tags.
    """
    album = item.get("album") or {}
    artists = item.get("artists") or []
    return {
        "uri": item.get("uri"),
        "name": item.get("name"),
        "artists": [a.get("name") for a in artists if isinstance(a, dict)],
        "album": album.get("name") if isinstance(album, dict) else None,
    }


# ---------------------------------------------------------------------------
# AI Task calls
# ---------------------------------------------------------------------------

def _is_generic_artist(name: str) -> bool:
    """True for placeholder 'artist' names used on compilations/soundtracks
    (e.g. "Various Artists") -- useless for artist-based matching since
    every track on the compilation shares the same one."""
    return name.strip().lower() in GENERIC_ARTIST_MARKERS


def _library_summary(library: list[dict[str, Any]]) -> tuple[str, str, int, str]:
    """Build a library overview for the AI: the COMPLETE artist roster
    (every distinct artist, not a top-N sample) so mood/prompt matching
    isn't limited to whichever artists happened to be most-represented,
    a sample of individual tracks for title-keyword discovery, and a
    separate list of compilation albums (tracks credited to a generic
    "artist" like Various Artists, where album name -- not artist -- is
    the only usable signal).

    Returns (artist_summary, sample_lines, sample_size, compilation_summary).
    """
    artist_counts: Counter[str] = Counter()
    compilation_album_counts: Counter[str] = Counter()
    for track in library:
        artists = track["artists"]
        if artists and all(_is_generic_artist(a) for a in artists):
            if track.get("album"):
                compilation_album_counts[track["album"]] += 1
            continue
        for artist in artists:
            if not _is_generic_artist(artist):
                artist_counts[artist] += 1

    all_artists = artist_counts.most_common()  # every distinct artist, most tracks first
    truncated = len(all_artists) > MAX_ARTISTS_IN_SUMMARY
    shown_artists = all_artists[:MAX_ARTISTS_IN_SUMMARY]
    artist_summary = ", ".join(f"{a} ({c})" for a, c in shown_artists) or "no artists found"
    if truncated:
        artist_summary += (
            f", ... ({len(all_artists) - MAX_ARTISTS_IN_SUMMARY} more artists not "
            "shown -- treat the above as the artists to choose from, there may be "
            "others in the library not listed here)"
        )

    sample_size = min(MOOD_SAMPLE_SIZE, len(library))
    sample = random.sample(library, sample_size) if sample_size else []
    sample_lines = "\n".join(_format_sample_line(t) for t in sample)

    compilation_summary = ""
    if compilation_album_counts:
        all_comp_albums = compilation_album_counts.most_common()
        shown_comp = all_comp_albums[:MAX_COMPILATION_ALBUMS_LISTED]
        compilation_summary = ", ".join(f"{a} ({c})" for a, c in shown_comp)

    return artist_summary, sample_lines, sample_size, compilation_summary


def _format_sample_line(track: dict[str, Any]) -> str:
    artists = ", ".join(track["artists"]) or "Unknown artist"
    album_suffix = f" ({track['album']})" if track.get("album") else ""
    return f"- {artists} - {track['name']}{album_suffix}"



async def _discover_moods(
    hass: HomeAssistant,
    library: list[dict[str, Any]],
    ai_task_entity_id: str,
    mood_count_min: int,
    mood_count_max: int,
) -> tuple[dict[str, dict[str, Any]], str]:
    artist_summary, sample_lines, sample_size, compilation_summary = _library_summary(
        library
    )

    compilation_block = ""
    if compilation_summary:
        compilation_block = f"""

Compilation/soundtrack albums (these tracks are credited to a generic
"artist" like Various Artists, so artist_hints can't identify them --
album name is the only usable signal for these; if one fits a mood, put
matching words from its name into "title_keywords" instead):
{compilation_summary}"""

    instructions = f"""You are picking mood-based playlist categories for a home music
library. This library has no genre tags attached to it, so you must rely
on your own general knowledge of these specific artists' styles to judge
what fits each mood. Only use artists and tracks actually listed below --
do not invent ones that aren't represented in this data.

Complete list of artists in the library, with track counts (this is every
distinct artist, not a sample -- use the full breadth of it, not just the
first few you recognize): {artist_summary}

Sample of {sample_size} tracks from the library (for spotting recurring
words in titles/albums, e.g. "Live", "Acoustic", "Christmas"):
{sample_lines}{compilation_block}

Propose between {mood_count_min} and {mood_count_max} mood categories that
meaningfully partition this library's real content (e.g. "Late Night Wind
Down", "Sunday Morning Coffee", "Workout Energy" -- but only if the artists
above actually support that mood based on what you know of their music).
For each mood, consider the full artist list above, not just the most
common few -- a mood can and should draw on lesser-represented artists too
if they fit better than the most-represented ones.

Respond with ONLY a JSON array and nothing else -- no prose, no markdown
code fences. Each element must look like:
{{"name": "Short Mood Name", "description": "one sentence", "match_mode": "artist", "artist_hints": ["Artist A", "Artist B"], "title_keywords": ["acoustic", "live"], "energy": "low|medium|high"}}

"match_mode" controls how strictly this mood matches -- pick exactly one:
- "artist": match any track BY these artists (their entire catalog, not
  just some tracks). Use this for broad style/mood requests where most of
  an artist's output shares that quality (e.g. "upbeat", "90s rock").
- "title": match only tracks whose title/album literally contains one of
  "title_keywords". Use this when the mood is about specific content that
  varies track-by-track within an artist's catalog -- e.g. an artist with
  a mixed catalog (a classical composer who writes for many different
  instruments, a band with both acoustic and electric songs) where only
  some of their tracks actually fit.
- "both": match on artist OR title. Use only when you're confident the
  artists listed are narrowly focused enough that their whole catalog
  fits, AND you also have good literal title keywords as a bonus signal.

Default to "artist" for genuinely broad moods. Use "title" whenever the
mood depends on specific content (instrumentation, era-specific wording,
etc.) rather than an artist's overall style -- being wrong here means
tracks that don't actually fit the mood get included.

For "artist_hints": list up to {MAX_ARTIST_HINTS_PER_MOOD} artists per
mood, prioritizing the ones you're most confident about first. You have
the complete artist list above, not just a sample, so be thorough --
don't limit yourself to only the handful with the highest track counts."""

    response = await hass.services.async_call(
        "ai_task",
        "generate_data",
        {
            "task_name": "Discover mood playlists",
            "instructions": instructions,
            "entity_id": ai_task_entity_id,
        },
        blocking=True,
        return_response=True,
    )
    raw_text = (response or {}).get("data", "")
    moods_list = _parse_json(raw_text, expect_list=True)

    moods: dict[str, dict[str, Any]] = {}
    for m in moods_list:
        name = m.get("name")
        if not name:
            continue
        moods[name] = _normalize_mood_dict(m)
    return moods, raw_text


async def _interpret_prompt(
    hass: HomeAssistant,
    library: list[dict[str, Any]],
    ai_task_entity_id: str,
    prompt: str,
) -> tuple[dict[str, Any], str]:
    artist_summary, sample_lines, sample_size, compilation_summary = _library_summary(
        library
    )

    compilation_block = ""
    if compilation_summary:
        compilation_block = f"""

Compilation/soundtrack albums (these tracks are credited to a generic
"artist" like Various Artists, so artist_hints can't identify them --
album name is the only usable signal for these; if one fits the request,
put matching words from its name into "title_keywords" instead):
{compilation_summary}"""

    instructions = f"""A user wants a playlist matching this request:
"{prompt}"

Here is what's actually in their music library -- only use this to decide
what matches, do not suggest anything not represented here. This library
has no genre tags, so use your own knowledge of these specific artists'
styles to judge what fits the request.

Complete list of artists in the library, with track counts (this is every
distinct artist, not a sample -- check the full list for a fit, not just
the first few you recognize): {artist_summary}

Sample of {sample_size} tracks from the library (for spotting recurring
words in titles/albums, e.g. "Live", "Acoustic", "Christmas"):
{sample_lines}{compilation_block}

Respond with ONLY a single JSON object and nothing else -- no prose, no
markdown code fences:
{{"match_mode": "artist", "artist_hints": ["Artist A", "Artist B"], "title_keywords": ["acoustic"], "energy": "low|medium|high"}}

"match_mode" determines how matching works -- pick exactly one, this is
not optional:
- "artist": every track BY the listed "artist_hints" will be included --
  their entire catalog, not just fitting tracks. Choose this ONLY for
  broad requests ("upbeat", "moody", "90s rock") where you're confident
  most of each listed artist's output shares that quality.
- "title": ONLY tracks whose title or album literally contains one of
  "title_keywords" will be included; "artist_hints" is ignored entirely
  in this mode. Choose this for narrow/specific requests -- instrumentation
  ("piano", "acoustic", "instrumental"), a specific era/style word, or
  anything else that likely varies track-by-track within an artist's
  catalog rather than applying to everything they've made. This includes
  any composer, classical artist, or act with a musically mixed catalog --
  even if you can name an artist who plays piano, if they also have
  string, choral, or other works, "artist" mode would incorrectly include
  those too.
- "both": tracks matching EITHER signal are included. Use only when you
  have both a confidently narrow artist list AND reliable title keywords.

Default to "title" whenever there's genuine doubt about whether an
artist's whole catalog fits -- a smaller, accurate result beats a larger
one that includes tracks that don't match the request. If the request
names artists/styles not present above, still return the closest match
from what IS present, applying the same judgment.

For "artist_hints" in "artist" or "both" mode: list up to
{MAX_ARTIST_HINTS_PER_MOOD} matching artists, prioritizing your most
confident ones first. You have the complete artist list above, not just a
sample -- check all of it, not only the most-represented few."""

    response = await hass.services.async_call(
        "ai_task",
        "generate_data",
        {
            "task_name": "Interpret playlist prompt",
            "instructions": instructions,
            "entity_id": ai_task_entity_id,
        },
        blocking=True,
        return_response=True,
    )
    raw_text = (response or {}).get("data", "")
    parsed = _parse_json(raw_text, expect_list=False)
    return _normalize_mood_dict(parsed if isinstance(parsed, dict) else {}), raw_text


VALID_MATCH_MODES = ("artist", "title", "both")


def _normalize_mood_dict(m: dict[str, Any]) -> dict[str, Any]:
    match_mode = m.get("match_mode")
    if match_mode not in VALID_MATCH_MODES:
        # Model omitted or mis-typed it -- fall back to "both" rather than
        # silently matching nothing, but this is the least strict option,
        # so a well-behaved model should always be setting this explicitly.
        match_mode = "both"
    return {
        "description": m.get("description", ""),
        "match_mode": match_mode,
        "artist_hints": [a.lower() for a in m.get("artist_hints", []) if a],
        "title_keywords": [k.lower() for k in m.get("title_keywords", []) if k],
        "energy": m.get("energy", "medium"),
    }


def _parse_json(raw_text: str, expect_list: bool) -> Any:
    """Parse JSON out of the AI's response, tolerating code fences/prose."""
    text = raw_text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    pattern = r"\[.*\]" if expect_list else r"\{.*\}"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return [] if expect_list else {}


# ---------------------------------------------------------------------------
# Local matching
# ---------------------------------------------------------------------------

def _tracks_matching_mood(
    library: list[dict[str, Any]], mood: dict[str, Any]
) -> list[dict[str, Any]]:
    """Match tracks according to the mood's declared match_mode.

    match_mode is enforced in code, not left to the AI's discretion at
    matching time -- the AI picks "artist" (broad, whole-catalog), "title"
    (strict, literal keyword in track/album name), or "both" when it
    generates the mood/prompt interpretation, and this function honors
    that choice exactly rather than blending signals in a way that could
    re-admit tracks the "title" mode was specifically meant to exclude.

    Artist matching resolves each hint against the library's real artist
    names with an EXACT (case-insensitive) match first; substring matching
    is only used as a fallback for a hint that doesn't exactly match any
    real artist, to catch minor formatting differences (e.g. the AI
    dropping "The") without the false-positive risk of substring-matching
    every hint against every artist (a short hint could otherwise
    accidentally match an unrelated artist whose name happens to contain
    it as a substring).

    Returned tracks carry "_artist_hit"/"_title_hit" flags (regardless of
    match_mode) so the caller can rank title-confirmed matches -- stronger
    evidence than "this track's artist was hinted at" -- ahead of
    artist-only matches when only some candidates are needed.

    No genre data is available through Music Assistant's Home Assistant
    integration, so artist name and title text are the only signals to
    match on at all.
    """
    match_mode = mood.get("match_mode", "both")
    artist_hints = [h.strip() for h in mood.get("artist_hints", []) if h and h.strip()]
    title_keywords = mood.get("title_keywords", [])
    if not artist_hints and not title_keywords:
        return []

    library_artist_names = {a.lower() for t in library for a in t["artists"]}
    resolved_hints: set[str] = set()
    for hint in artist_hints:
        if hint in library_artist_names:
            resolved_hints.add(hint)
            continue
        # No exact match -- fall back to substring, but only add real
        # library artist names this way, never the raw (unresolved) hint.
        for name in library_artist_names:
            if hint in name or name in hint:
                resolved_hints.add(name)

    matches = []
    for track in library:
        track_artists = [a.lower() for a in track["artists"]]
        title_text = f"{track['name']} {track.get('album') or ''}".lower()

        artist_hit = bool(resolved_hints) and any(
            a in resolved_hints for a in track_artists
        )
        title_hit = bool(title_keywords) and any(kw in title_text for kw in title_keywords)

        if match_mode == "artist":
            hit = artist_hit
        elif match_mode == "title":
            hit = title_hit
        else:  # "both"
            hit = artist_hit or title_hit

        if hit:
            matches.append({**track, "_artist_hit": artist_hit, "_title_hit": title_hit})
    return matches


def _tracks_matching_mood_staged(
    library: list[dict[str, Any]], mood: dict[str, Any]
) -> tuple[list[dict[str, Any]], str]:
    """Try the mood's declared match_mode first; if that finds nothing, try
    the other signal (artist<->title) before giving up to a fully random
    sample -- a softer landing than jumping straight from "0 matches" to
    "ignore the request entirely."

    Returns (matches, stage):
      "primary"   -- the declared match_mode found results, as normal.
      "secondary" -- match_mode found nothing, but the other signal
                     (artist_hints or title_keywords, whichever the
                     declared mode wasn't using) did.
      "none"      -- neither signal matched anything; caller should fall
                     back to a fully random library sample.

    Only meaningful for match_mode "artist" or "title" -- "both" already
    tries both signals, so there's no distinct fallback left to attempt.
    """
    primary = _tracks_matching_mood(library, mood)
    if primary:
        return primary, "primary"

    match_mode = mood.get("match_mode", "both")
    artist_hints = mood.get("artist_hints", [])
    title_keywords = mood.get("title_keywords", [])

    if match_mode == "title" and artist_hints:
        secondary = _tracks_matching_mood(library, {**mood, "match_mode": "artist"})
        if secondary:
            return secondary, "secondary"
    elif match_mode == "artist" and title_keywords:
        secondary = _tracks_matching_mood(library, {**mood, "match_mode": "title"})
        if secondary:
            return secondary, "secondary"

    return [], "none"
