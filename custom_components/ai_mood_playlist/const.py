"""Constants for AI Mood Playlist."""

DOMAIN = "ai_mood_playlist"

CONF_MA_CONFIG_ENTRY = "ma_config_entry_id"
CONF_AI_TASK_ENTITY = "ai_task_entity_id"
CONF_REFRESH_INTERVAL_HOURS = "refresh_interval_hours"
CONF_AUTO_DISCOVER_AFTER_REFRESH = "auto_discover_after_refresh"

DEFAULT_TRACK_COUNT = 15
DEFAULT_REFRESH_INTERVAL_HOURS = 24  # 0 disables periodic refresh
DEFAULT_AUTO_DISCOVER_AFTER_REFRESH = True
DEFAULT_MOOD_COUNT_MIN = 6
DEFAULT_MOOD_COUNT_MAX = 10
LIBRARY_PAGE_SIZE = 500
MOOD_SAMPLE_SIZE = 250
# Safety ceiling on how many unique artists get sent to the AI. We send the
# FULL artist roster (not a top-N sample) so mood/prompt matching can be
# comprehensive rather than limited to whichever artists happened to be
# most-represented -- this cap only guards against pathological libraries
# with an enormous number of distinct artists.
MAX_ARTISTS_IN_SUMMARY = 3000
# Advisory cap communicated to the AI so its response stays bounded in size
# even for a very broad mood/prompt matching many artists; not enforced in
# code, just keeps output token usage predictable.
MAX_ARTIST_HINTS_PER_MOOD = 80
MAX_LOG_ENTRIES = 50
MAX_LOG_IN_SENSOR = 10

# Artist names that mean "not a real performer" -- tracks credited to one
# of these need album name (not artist) as their matching signal, since
# every compilation/soundtrack track otherwise shares the same useless
# "artist".
GENERIC_ARTIST_MARKERS = frozenset(
    {
        "various artists",
        "various",
        "va",
        "soundtrack",
        "original soundtrack",
        "original motion picture soundtrack",
        "compilation",
        "ost",
    }
)
MAX_COMPILATION_ALBUMS_LISTED = 500

# How many recently-queued track URIs to remember, across all moods/
# prompts, so back-to-back plays don't just repeat the same tracks.
MAX_RECENT_PLAYS = 300

SIGNAL_MOODS_UPDATED = f"{DOMAIN}_moods_updated"
SIGNAL_STATUS_UPDATED = f"{DOMAIN}_status_updated"

NO_MOOD_OPTION = "(run Discover Moods first)"
NO_PLAYER_OPTION = "(no Music Assistant speakers found)"

STATE_IDLE = "idle"
STATE_OK = "ok"
STATE_ERROR = "error"
STATE_RUNNING = "running"
