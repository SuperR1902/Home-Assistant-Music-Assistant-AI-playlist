# AI Mood Playlist

A Home Assistant custom integration that builds mood-based playlists
**from your real, locally-indexed Music Assistant library** — no cloud
service needed, no hallucinated tracks you don't own, and **no YAML
required anywhere** — setup, daily use, and troubleshooting are all done
through the Home Assistant GUI.

## How it works

1. **Read** your actual library from Music Assistant.
2. **Ask the AI** (via your existing AI Task entity) to map artists in your
   library to moods using its own knowledge of those artists, or to
   interpret a free-text request you type in the same way. Music
   Assistant's Home Assistant integration doesn't expose genre tags
   through any current action, even for well-tagged files, so this relies
   on artist-name recognition (and any obvious keywords in track/album
   titles) rather than genre metadata.
3. **Filter locally**: tracks are picked from your already-fetched
   library by matching artist names (primary) or a title keyword (secondary).
   Every track queued came from your library, so it's guaranteed to exist.

## Prerequisites

- Home Assistant 2025.11+
- Music Assistant integration configured, with your local library added
- An AI Task entity configured (Settings → your AI integration → add
  "AI Task")

## Installation

1. HACS → three-dot menu → **Custom repositories**
2. Add this repo, category **Integration**
3. Install "AI Mood Playlist", restart Home Assistant
4. **Settings → Devices & Services → Add Integration → AI Mood Playlist**
   — the integration has its own icon (music note + sparkle), shown here
   and on its device page automatically. This requires **Home Assistant
   2026.3+**; on older versions the icon just falls back to a generic
   placeholder, everything else still works.
5. In the setup form, pick:
   - Your **Music Assistant** config entry (dropdown)
   - Your **AI Task** entity (dropdown)
   - A **refresh interval** in hours for automatic re-indexing (`0` to
     disable and index manually instead)
   - Whether to **auto-discover moods** after each refresh

That's the entire setup — everything from here on is entity controls, no
files to edit.

## Using it — everything lives on one device page

Go to **Settings → Devices & Services → AI Mood Playlist → (the device)**.
You'll see these entities, all controllable directly from the GUI:

| Entity | What it does |
|---|---|
| `select.*_mood` | Dropdown of moods discovered so far |
| `select.*_target_speaker` | Dropdown of your Music Assistant speakers (auto-populated) |
| `text.*_prompt` | Type a free-text request here to override the mood, e.g. *"moody 90s trip-hop for a rainy evening"* |
| `number.*_track_count` | How many tracks to queue |
| `switch.*_clear_queue_first` | On = replace the queue, off = add to it |
| `button.*_play` | Plays the prompt (if typed) or the selected mood, on the selected speaker |
| `button.*_refresh_library_now` | Force a re-index without waiting for the schedule |
| `button.*_discover_moods_now` | Force mood discovery without waiting for the schedule |
| `sensor.*_status` | Current status + recent history + now-playing — see Troubleshooting below |

To put these on a dashboard: open the device page and use its **Add to
dashboard** button (top right), or add an **Entities** card and pick them
individually from the entity picker — both fully mouse/GUI-driven, no
YAML.

Typical flow: press **Refresh Library Now** once after setup, then
**Discover Moods Now** (you'll get a notification listing the moods it
found — check the bell icon top-right), then pick a mood (or type a
prompt), pick a speaker, and press **Play**.

Your library cache, discovered moods, and recent-plays history are saved
to disk (in HA's own `.storage` folder) after every successful
refresh/discovery/play, so a Home Assistant restart — or changing a
setting in Configure, which reloads the integration — won't force you to
start over or immediately repeat what you just heard.

## Playlist quality & UX features

Five improvements added after initial testing surfaced real gaps:

- **Compilation/Various Artists handling.** Tracks credited to a generic
  "artist" (Various Artists, VA, Soundtrack, OST, etc.) are pulled out of
  the normal artist roster — matching by artist name is meaningless for
  these, since every track on the compilation shares the same one.
  Instead, the AI gets a separate list of compilation album names (with
  track counts) and is told to use `title_keywords` against those when
  relevant, e.g. recognizing a holiday compilation by name for a
  "Christmas" request.
- **Staged fallback.** If a mood/prompt's declared `match_mode` finds zero
  matches (e.g. the AI's `artist_hints` don't actually exist in your
  library, or `title_keywords` don't appear anywhere), the code now tries
  the *other* signal before giving up entirely — only falling back to a
  fully random library-wide sample if neither signal turns up anything.
  Check `sensor.*_status` → `last_message` for a note when this happened;
  it's not an error, just a softer landing than an all-or-nothing jump to
  random.
- **Anti-repetition.** Recently-queued track URIs (last 300, across all
  moods/prompts, persisted to disk) are deprioritized in future
  selections — back-to-back plays of the same mood won't just return the
  same 15 tracks. If a mood's matching pool is small, recently-played
  tracks still get reused rather than refusing to play — repetition is
  minimized, not prevented outright, so a niche mood/prompt never comes up
  empty.
- **Now-playing context.** `sensor.*_status` attributes now include
  `now_playing_source` (`"mood"` or `"prompt"`), `now_playing_value` (the
  mood name or prompt text), `now_playing_speaker`, and
  `now_playing_since` — so you can tell what's actually playing where
  without it being buried in the log.
- **Discover Moods notification.** A dismissible HA notification now
  appears after successful mood discovery, listing the moods found, so
  you don't have to manually check the sensor.

## Troubleshooting — what to send me

**`sensor.*_status`** is the fastest way to check what happened: open its
more-info dialog and look at **Attributes** — `last_action`,
`last_message`, and a `recent_log` list of the last 10 events (refreshes,
discoveries, plays, and any errors) are all there in plain English. Its
main state is `idle` / `running` / `ok` / `error`.

**For anything more detailed**, download the full diagnostics report:
**Settings → Devices & Services → AI Mood Playlist → three-dot menu on the
entry → Download Diagnostics**. This is a JSON file (no YAML editing, just
a click) containing:
- current config and selections
- full status (including now-playing) + up to 50 recent log entries
- discovered moods, with their `match_mode`/`artist_hints`/`title_keywords`
  visible — useful for checking whether the AI chose the mode you'd expect
- library track count, unique artist count, how many recent plays are
  being tracked for anti-repetition, and a 5-track raw sample of what
  Music Assistant actually returned (useful if artist/title matching
  looks off)

Paste that file's contents to me and I can diagnose from it directly.

**If you need deeper HA core logs** (rare — the status sensor usually
covers it): go to **Developer Tools → Actions**, search for
**`logger.set_level`**, and set `custom_components.ai_mood_playlist` to
`debug` — this is a live GUI action, no `configuration.yaml` editing or
restart needed. Then check **Settings → System → Logs**.

## Limitations / things worth knowing

- **No genre metadata, by design of the HA↔Music Assistant integration.**
  This was confirmed through actual testing (not just docs): Music
  Assistant's `get_library` action returns a lean summary — name, URI,
  artists, album — for every media type, with no genre field at all,
  regardless of how well your files are tagged. There's no current
  Home Assistant action that exposes it either (confirmed via a Music
  Assistant feature-request thread asking for exactly this). So matching
  works by **artist name** and by keywords spotted literally in track/album
  titles — no genre tags to lean on. If neither matches, playback falls
  back to a random sample of your whole library.
- **Artist matching is whole-catalog, not per-track — enforced in code as
  of this version, not just prompted.** Matching an artist under
  `match_mode: "artist"` pulls in *everything* by them; this showed up in
  testing where a "piano" request also returned violin and choral pieces
  by the same composer, even after the AI was instructed to be careful
  about it. Since a text instruction alone wasn't reliably followed, the
  code now enforces the mode directly: `match_mode: "title"` **ignores
  `artist_hints` entirely** at match time, restricting results to literal
  keyword hits in track/album titles — verified with an isolated test
  reproducing that exact composer/piano/violin scenario. This still
  depends on the model correctly *choosing* `"title"` vs `"artist"` for a
  given request; if a narrow request still pulls in unrelated pieces,
  check the diagnostics `moods` section for which `match_mode` was
  actually chosen — that would mean the judgment call was wrong, not that
  the enforcement failed, and is worth reporting back to tighten the
  prompt further.
- **Full artist roster, not a sample.** Earlier versions only showed the
  AI the top 40 most-represented artists plus a random 250-track sample —
  meaning any artist outside those wasn't visible to the model at all.
  The AI now receives every distinct artist in your library (capped at
  3000 as a safety ceiling for extreme cases), so mood/prompt matching can
  draw on lesser-represented artists too, not just whichever happened to
  have the most tracks.
- **Diverse track selection.** When a mood/prompt matches multiple
  artists, tracks are now picked round-robin across them rather than
  randomly from the combined pool — otherwise whichever matched artist
  has the biggest catalog would dominate the queue. Title-confirmed
  matches (from `title_keywords`) are also filled first, ahead of
  artist-only matches, when there are more candidates than requested
  tracks, since a literal title match is stronger evidence than "this
  track's artist was hinted at."
  Practical effect either way: mood/prompt matching is only as good as
  how recognizable your artists are to the model, and how many distinct
  artists you have — a library with 50 tracks from 3 artists won't
  partition into moods nearly as well as one spanning hundreds.
- **Periodic refresh is an in-process timer**: its *schedule* (the
  countdown to the next auto-refresh) resets if Home Assistant restarts or
  you reload the integration — but the *data* from your last refresh
  (library cache + discovered moods) is persisted to disk and survives
  restarts, so nothing is lost, only the countdown restarts. If you need a
  fixed time of day (e.g. "always 3am") rather than "every N hours since
  last restart", set the interval to `0` in Configure and call
  `ai_mood_playlist.refresh_library` / `discover_moods` from a normal
  time-triggered automation instead — both remain available as services
  for this and other automation use.
- **Data sent to the AI:** your complete artist roster (with track
  counts), up to ~250 sample `artist - title (album)` lines from your
  library, compilation album names if you have any (Various
  Artists/soundtrack-credited tracks), and your typed prompt when using
  Play with text. No account info, no full library dump. Use a local AI
  Task provider (Ollama) if you'd rather nothing leave your network.
- This is a working starting point, not a polished HACS release — error
  handling covers the common failure modes rather than every edge case.
  The status sensor and diagnostics download exist specifically so any
  issues are easy to report back precisely.

## Design history

The original design assumed Music Assistant would expose genre tags per
track through Home Assistant's `get_library` action, with artist-name
matching as a fallback for untagged libraries. Testing against a real
10,800+ track library showed 0 tracks returning genre data — turned out
Home Assistant's `get_library` action doesn't expose genre metadata for
*any* library, tagged or not (confirmed against HA's own docs and a Music
Assistant feature-request thread asking for exactly this capability). So
the "fallback" became the actual mechanism: the AI is now asked directly
to use its own knowledge of specific artists in your library to judge
mood fit, rather than being given genre tags to work from at all. This is
reflected in the code and prompts as they exist now, not left as a
theoretical fallback path.

## License

MIT
