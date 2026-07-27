"""Voice command intent registry.

A small, deterministic router - not a statistical classifier - that checks
a normalized transcript against a fixed, ordered list of intents, each with
its own matcher (returns a match value, or None/False for no match) and
handler. Intents work without any pre-configured automation. If nothing
matches, try_builtin_command() returns None and the caller falls through to
automation-trigger fuzzy matching in modules/automations.py.

Adding a new built-in command means adding one matcher/handler pair and one
line in INTENTS - the rest of the pipeline (STT -> here -> speak response)
doesn't change.
"""

import random
import re
from difflib import SequenceMatcher

from modules.music_output import list_tracks, get_track_path, set_command as set_music_command
from modules.playlists import list_playlists, play_playlist

MATCH_THRESHOLD = 0.5


def _normalize(text):
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


def _speak(text, output):
    if output == "browser":
        from modules.voice import synthesize_speech
        import uuid
        return synthesize_speech(text, output_name=f"ptt-{uuid.uuid4().hex[:8]}.wav")
    from modules.voice import sentinel_say
    return sentinel_say(text)


def _log(message, ok, metadata=None):
    # Never pass the raw transcript (the "phrase" key) into metadata here -
    # the activity log is persisted to disk indefinitely, and retaining a
    # verbatim record of everything spoken to Sentinel would violate the
    # no-voice-retention policy just as much as keeping the audio would.
    from modules.activity_log import log_event
    log_event("automations", "builtin_command", message, severity="info" if ok else "warning", metadata=metadata or {})


# ---------------------------------------------------------------------
# Intent: stop music
# ---------------------------------------------------------------------

STOP_PHRASES = {
    "stop", "stop music", "stop the music", "pause music", "pause the music",
    "stop playing", "sentinel stop", "stop playing music",
}


def _match_stop(normalized, phrase):
    return True if normalized in STOP_PHRASES else None


def _handle_stop(phrase, output, match):
    if output == "pi":
        from modules.voice import stop_music_on_pi
        stop_result = stop_music_on_pi()
    else:
        stop_result = {"ok": True, "command": set_music_command("stop")}

    results = [{"type": "music_stop", "ok": bool(stop_result.get("ok", True)), "result": stop_result}]
    speak_result = _speak("Stopping the music.", output)
    results.append({"type": "speak", "ok": bool(speak_result.get("ok")), "phrase": "Stopping the music.", "result": speak_result})

    ok = all(r.get("ok") for r in results)
    _log(f"Built-in stop command ({output})", ok)
    return {"ok": ok, "builtin": "stop", "results": results}


# ---------------------------------------------------------------------
# Intent: set lights brightness ("Sentinel, set lights to 50 percent")
# Checked before the color intent since both start with "set lights to" -
# this one requires digits, color requires non-digit words, so they never
# both match the same phrase.
# ---------------------------------------------------------------------

BRIGHTNESS_PATTERN = re.compile(
    r"^(?:sentinel[,]?\s+)?set\s+(?:the\s+)?(?:lights?|brightness)\s+to\s+(\d{1,3})\s*(?:percent|%)?$",
    re.IGNORECASE,
)


def _match_brightness(normalized, phrase):
    m = BRIGHTNESS_PATTERN.match(phrase.strip())
    if not m:
        return None
    pct = int(m.group(1))
    return pct if 0 <= pct <= 100 else None


def _current_light_xy():
    """set_lights() always computes an xy from its color= param (default
    'blue') unless one is passed explicitly - read the first target light's
    actual current xy so a brightness-only command doesn't also reset the
    color."""
    from modules.hue import hue_get, _target_light_ids
    try:
        ids = _target_light_ids()
        if not ids:
            return None
        lights = hue_get("/lights")
        return lights.get(ids[0], {}).get("state", {}).get("xy")
    except Exception:
        return None


def _handle_brightness(phrase, output, pct):
    from modules.hue import set_lights
    bri = max(1, min(254, round(pct / 100 * 254)))
    xy = _current_light_xy()
    result = set_lights(bri=bri, xy=xy) if xy else set_lights(bri=bri)
    ok_lights = bool(result.get("ok"))

    results = [{"type": "hue_lights", "ok": ok_lights, "result": result}]
    spoken = f"Brightness set to {pct} percent." if ok_lights else "I couldn't reach the lights."
    speak_result = _speak(spoken, output)
    results.append({"type": "speak", "ok": bool(speak_result.get("ok")), "phrase": spoken, "result": speak_result})

    ok = ok_lights and bool(speak_result.get("ok"))
    _log(f"Built-in brightness command: {pct}% ({output})", ok, {"percent": pct})
    return {"ok": ok, "builtin": "brightness", "percent": pct, "results": results}


# ---------------------------------------------------------------------
# Intent: set lights color ("Sentinel, set lights to red")
# ---------------------------------------------------------------------

COLOR_PATTERN = re.compile(
    r"^(?:sentinel[,]?\s+)?set\s+(?:the\s+)?lights?\s+to\s+([a-z ]+)$",
    re.IGNORECASE,
)
# Matches modules.hue._xy_for_color()'s existing palette exactly - reusing
# it means the voice command and the Hue Scenes color picker always agree
# on what "red" or "purple" actually looks like.
KNOWN_COLORS = {"red", "blue", "green", "yellow", "purple", "orange", "pink", "white", "cyan"}


def _match_color(normalized, phrase):
    m = COLOR_PATTERN.match(phrase.strip())
    if not m:
        return None
    word = m.group(1).strip().lower()
    return word if word in KNOWN_COLORS else None


def _handle_color(phrase, output, color):
    from modules.hue import set_lights
    result = set_lights(color=color)
    ok_lights = bool(result.get("ok"))

    results = [{"type": "hue_lights", "ok": ok_lights, "result": result}]
    spoken = f"Lights set to {color}." if ok_lights else "I couldn't reach the lights."
    speak_result = _speak(spoken, output)
    results.append({"type": "speak", "ok": bool(speak_result.get("ok")), "phrase": spoken, "result": speak_result})

    ok = ok_lights and bool(speak_result.get("ok"))
    _log(f"Built-in color command: {color} ({output})", ok, {"color": color})
    return {"ok": ok, "builtin": "color", "color": color, "results": results}


# ---------------------------------------------------------------------
# Intent: play songs by an artist, optionally scoped to one album
# ("play songs by Creedence Clearwater Revival" / "play songs by AC DC
# from the greatest hits"). Checked before the generic play-by-name intent
# since "play songs by X" would otherwise be tried (and fail) as a literal
# track/playlist title first.
# ---------------------------------------------------------------------

ARTIST_ALBUM_PATTERN = re.compile(
    r"^(?:sentinel[,]?\s+)?play\s+(?:songs?|music)\s+by\s+(.+?)\s+from\s+(?:the\s+)?(.+?)(?:\s+album)?$",
    re.IGNORECASE,
)
ARTIST_ONLY_PATTERN = re.compile(
    r"^(?:sentinel[,]?\s+)?play\s+(?:songs?|music)\s+by\s+(.+)$",
    re.IGNORECASE,
)


def _best_string_match(query, candidates):
    query_n = _normalize(query)
    if not candidates or not query_n:
        return None
    best, best_score = None, 0.0
    for c in candidates:
        c_n = _normalize(c)
        score = SequenceMatcher(None, query_n, c_n).ratio()
        if query_n in c_n or c_n in query_n:
            score = max(score, 0.85)
        if score > best_score:
            best, best_score = c, score
    return (best, best_score) if best_score >= MATCH_THRESHOLD else None


def _match_play_by_artist(normalized, phrase):
    stripped = phrase.strip()
    m = ARTIST_ALBUM_PATTERN.match(stripped)
    if m:
        return {"artist_query": m.group(1).strip(), "album_query": m.group(2).strip()}
    m = ARTIST_ONLY_PATTERN.match(stripped)
    if m:
        return {"artist_query": m.group(1).strip(), "album_query": None}
    return None


def _handle_play_by_artist(phrase, output, ctx):
    tracks = list_tracks()
    artist_match = _best_string_match(ctx["artist_query"], sorted({t["artist"] for t in tracks if t.get("artist")}))
    if not artist_match:
        return {"ok": False, "builtin": "play_artist", "error": f'No artist matching "{ctx["artist_query"]}"', "results": []}
    artist_name, _artist_score = artist_match
    artist_tracks = [t for t in tracks if _normalize(t.get("artist", "")) == _normalize(artist_name)]

    album_name = None
    if ctx["album_query"]:
        album_match = _best_string_match(ctx["album_query"], sorted({t["album"] for t in artist_tracks if t.get("album")}))
        if album_match:
            album_name, _album_score = album_match
            artist_tracks = [t for t in artist_tracks if _normalize(t.get("album", "")) == _normalize(album_name)]

    if not artist_tracks:
        return {"ok": False, "builtin": "play_artist", "error": "No matching tracks found", "results": []}

    if album_name:
        queue_tracks = sorted(artist_tracks, key=lambda t: (t.get("track_number") or 999, t["name"]))
        spoken_scope = f"the {album_name} album by {artist_name}"
    else:
        queue_tracks = list(artist_tracks)
        random.shuffle(queue_tracks)
        spoken_scope = f"songs by {artist_name}"

    queue = [t["file"] for t in queue_tracks]

    if output == "pi":
        # Same limitation as playlist voice commands - no background
        # continuation watcher on the Pi yet, so only the first track plays
        # there. Full sequential playback works from the browser.
        from modules.voice import play_music_on_pi
        path = get_track_path(queue[0])
        play_result = play_music_on_pi(path) if path else {"ok": False, "error": "Track file missing"}
    else:
        play_result = {"ok": True, "command": set_music_command("play", file=queue[0], after_track="queue", queue=queue)}

    results = [{"type": "music_play", "ok": bool(play_result.get("ok", True)), "result": play_result}]
    spoken = f"Playing {spoken_scope}."
    speak_result = _speak(spoken, output)
    results.append({"type": "speak", "ok": bool(speak_result.get("ok")), "phrase": spoken, "result": speak_result})

    ok = all(r.get("ok") for r in results)
    _log(f"Built-in play-by-artist command: {spoken_scope} ({output}, {len(queue)} tracks)", ok,
         {"artist": artist_name, "album": album_name, "track_count": len(queue)})
    return {"ok": ok, "builtin": "play_artist", "artist": artist_name, "album": album_name, "track_count": len(queue), "results": results}


# ---------------------------------------------------------------------
# Intent: play track or playlist by name
# ---------------------------------------------------------------------

PLAY_PATTERN = re.compile(
    r"^(?:sentinel[,]?\s+)?play\s+(?:the\s+song\s+|the\s+track\s+)?(.+?)(?:\s+song)?$",
    re.IGNORECASE,
)


def _best_track_match(query):
    tracks = list_tracks()
    query_n = _normalize(query)
    if not tracks or not query_n:
        return None
    best, best_score = None, 0.0
    for track in tracks:
        name_n = _normalize(track["name"])
        score = SequenceMatcher(None, query_n, name_n).ratio()
        if query_n in name_n or name_n in query_n:
            score = max(score, 0.85)
        if score > best_score:
            best, best_score = track, score
    return (best, best_score) if best_score >= MATCH_THRESHOLD else None


def _best_playlist_match(query):
    lists = [p for p in list_playlists() if p["tracks"]]
    query_n = _normalize(query)
    if not lists or not query_n:
        return None
    best, best_score = None, 0.0
    for playlist in lists:
        name_n = _normalize(playlist["name"])
        score = SequenceMatcher(None, query_n, name_n).ratio()
        if query_n in name_n or name_n in query_n:
            score = max(score, 0.85)
        if score > best_score:
            best, best_score = playlist, score
    return (best, best_score) if best_score >= MATCH_THRESHOLD else None


def _match_play(normalized, phrase):
    m = PLAY_PATTERN.match(phrase.strip())
    if not m:
        return None
    query = m.group(1).strip()
    return query or None


def _handle_play(phrase, output, query):
    track_found = _best_track_match(query)
    playlist_found = _best_playlist_match(query)

    # Prefer whichever matched better - "play road trip mix" should hit a
    # playlist named that, while "play fortunate son" should hit the track,
    # even though both pools are checked every time.
    if playlist_found and (not track_found or playlist_found[1] >= track_found[1]):
        playlist, score = playlist_found
        if output == "pi":
            # Sequential multi-track continuation on the Pi would need a
            # background watcher to detect when each track ends - not built
            # yet, so voice-triggered playlists on the Pi play just the
            # first track for now (full continuation already works from
            # the browser, via the queue/advance mechanism the Music
            # page's Play button uses).
            from modules.voice import play_music_on_pi
            first_track = playlist["tracks"][0]
            path = get_track_path(first_track["file"])
            play_result = play_music_on_pi(path) if path else {"ok": False, "error": "Track file missing"}
        else:
            play_result = play_playlist(playlist["id"])

        results = [{"type": "music_play", "ok": bool(play_result.get("ok", True)), "result": play_result}]
        speak_result = _speak(f"Playing your {playlist['name']} playlist.", output)
        results.append({"type": "speak", "ok": bool(speak_result.get("ok")), "phrase": f"Playing your {playlist['name']} playlist.", "result": speak_result})

        ok = all(r.get("ok") for r in results)
        _log(f'Built-in play command: playlist "{playlist["name"]}" ({output})', ok,
             {"playlist_id": playlist["id"], "matched_score": round(score, 3)})
        return {"ok": ok, "builtin": "play", "playlist": playlist["name"], "matched_score": round(score, 3), "results": results}

    if not track_found:
        return {"ok": False, "builtin": "play", "error": f'No track or playlist matching "{query}"', "results": []}
    track, score = track_found

    if output == "pi":
        from modules.voice import play_music_on_pi
        path = get_track_path(track["file"])
        play_result = play_music_on_pi(path) if path else {"ok": False, "error": "Track file missing"}
    else:
        play_result = {"ok": True, "command": set_music_command("play", file=track["file"], after_track="stop")}

    results = [{"type": "music_play", "ok": bool(play_result.get("ok", True)), "result": play_result}]
    speak_result = _speak(f"Playing {track['name']}.", output)
    results.append({"type": "speak", "ok": bool(speak_result.get("ok")), "phrase": f"Playing {track['name']}.", "result": speak_result})

    ok = all(r.get("ok") for r in results)
    _log(f'Built-in play command: "{track["name"]}" ({output})', ok,
         {"track": track["file"], "matched_score": round(score, 3)})
    return {"ok": ok, "builtin": "play", "track": track["name"], "matched_score": round(score, 3), "results": results}


# ---------------------------------------------------------------------
# Intent: status reports - read-only, just speak an existing summary.
# Reuses modules.assessment's plain-English templates so the spoken
# answer always matches what Mission Control's own panels say.
# ---------------------------------------------------------------------

SECURITY_STATUS_PHRASES = {
    "security status", "security update", "give me a security update",
    "sentinel security status", "what is the security status", "how is security",
    "security report",
}
CLUSTER_STATUS_PHRASES = {
    "cluster status", "sentinel cluster status", "how is the cluster",
    "is everything online", "system status", "infrastructure status",
}
ALERTS_PHRASES = {
    "any alerts", "any alerts?", "are there any alerts", "sentinel any alerts",
    "latest alerts", "recent alerts", "any threats",
}
BACKUP_STATUS_PHRASES = {
    "backup status", "sentinel backup status", "how are backups",
    "backup update", "are backups ok", "are backups okay",
}


def _match_security_status(normalized, phrase):
    return True if normalized in SECURITY_STATUS_PHRASES else None


def _handle_security_status(phrase, output, match):
    from modules.wazuh import get_wazuh_summary
    from modules.assessment import soc_assessment
    spoken = soc_assessment(get_wazuh_summary())
    speak_result = _speak(spoken, output)
    ok = bool(speak_result.get("ok"))
    _log(f"Built-in security status command ({output})", ok)
    return {"ok": ok, "builtin": "security_status", "results": [{"type": "speak", "ok": ok, "phrase": spoken, "result": speak_result}]}


def _match_cluster_status(normalized, phrase):
    return True if normalized in CLUSTER_STATUS_PHRASES else None


def _handle_cluster_status(phrase, output, match):
    from modules.proxmox import get_cluster_health
    from modules.assessment import infrastructure_assessment
    spoken = infrastructure_assessment(get_cluster_health())
    speak_result = _speak(spoken, output)
    ok = bool(speak_result.get("ok"))
    _log(f"Built-in cluster status command ({output})", ok)
    return {"ok": ok, "builtin": "cluster_status", "results": [{"type": "speak", "ok": ok, "phrase": spoken, "result": speak_result}]}


def _match_alerts(normalized, phrase):
    return True if normalized in ALERTS_PHRASES else None


def _handle_alerts(phrase, output, match):
    from modules.wazuh import get_wazuh_summary
    from modules.assessment import threat_hunting_assessment
    spoken = threat_hunting_assessment(get_wazuh_summary())
    speak_result = _speak(spoken, output)
    ok = bool(speak_result.get("ok"))
    _log(f"Built-in alerts command ({output})", ok)
    return {"ok": ok, "builtin": "alerts", "results": [{"type": "speak", "ok": ok, "phrase": spoken, "result": speak_result}]}


def _match_backup_status(normalized, phrase):
    return True if normalized in BACKUP_STATUS_PHRASES else None


def _handle_backup_status(phrase, output, match):
    from modules.proxmox import get_backup_info
    import time as _time

    info = get_backup_info()
    tasks = info.get("recent_tasks") or []
    if not tasks:
        spoken = "No backup telemetry is available yet."
    else:
        latest = tasks[0]
        status = str(latest.get("status", "unknown"))
        started = latest.get("starttime")
        when = "recently"
        if started:
            hours_ago = (_time.time() - int(started)) / 3600
            when = "less than an hour ago" if hours_ago < 1 else f"about {round(hours_ago)} hour{'s' if round(hours_ago) != 1 else ''} ago"
        spoken = f"Last backup {'completed successfully' if status == 'OK' else f'reported status {status}'} {when}."

    speak_result = _speak(spoken, output)
    ok = bool(speak_result.get("ok"))
    _log(f"Built-in backup status command ({output})", ok)
    return {"ok": ok, "builtin": "backup_status", "results": [{"type": "speak", "ok": ok, "phrase": spoken, "result": speak_result}]}


# ---------------------------------------------------------------------
# Intent: device power ("Sentinel, wake up Heavy" / "Sentinel, shut down
# Light"). Delegates to modules.power.set_device_power(), which enforces
# the exact same restrictions as the dashboard's power buttons - disabled
# devices are refused, and shutdown only works where shutdown_method is
# explicitly "proxmox" (Argus and Osiris have none, deliberately).
# ---------------------------------------------------------------------

WAKE_PATTERN = re.compile(r"^(?:sentinel[,]?\s+)?wake\s+up\s+(.+)$", re.IGNORECASE)
SHUTDOWN_PATTERN = re.compile(r"^(?:sentinel[,]?\s+)?shut\s*down\s+(.+)$", re.IGNORECASE)


def _match_device_power(normalized, phrase):
    stripped = phrase.strip()
    m = WAKE_PATTERN.match(stripped)
    if m:
        return {"action": "wake", "query": m.group(1).strip()}
    m = SHUTDOWN_PATTERN.match(stripped)
    if m:
        return {"action": "shutdown", "query": m.group(1).strip()}
    return None


def _resolve_device_key(query):
    from modules.devices import load_devices
    devices = load_devices()
    query_n = _normalize(query)
    best_key, best_score = None, 0.0
    for key, dev in devices.items():
        name_n = _normalize(dev.get("name", key))
        score = SequenceMatcher(None, query_n, name_n).ratio()
        if query_n in name_n or name_n in query_n:
            score = max(score, 0.85)
        if score > best_score:
            best_key, best_score = key, score
    return (best_key, best_score) if best_score >= MATCH_THRESHOLD else None


def _handle_device_power(phrase, output, ctx):
    from modules.power import set_device_power
    resolved = _resolve_device_key(ctx["query"])
    if not resolved:
        return {"ok": False, "builtin": "device_power", "error": f'No device matching "{ctx["query"]}"', "results": []}
    key, score = resolved
    result = set_device_power(key, ctx["action"])
    ok_power = bool(result.get("ok"))
    device_name = result.get("name", ctx["query"])

    results = [{"type": "device_power", "ok": ok_power, "result": result}]
    verb = "Waking up" if ctx["action"] == "wake" else "Shutting down"
    spoken = f"{verb} {device_name}." if ok_power else (result.get("error") or f"Could not {ctx['action']} {device_name}.")
    speak_result = _speak(spoken, output)
    results.append({"type": "speak", "ok": bool(speak_result.get("ok")), "phrase": spoken, "result": speak_result})

    ok = ok_power and bool(speak_result.get("ok"))
    _log(f"Built-in device power command: {ctx['action']} {device_name} ({output})", ok,
         {"device": key, "action": ctx["action"], "matched_score": round(score, 3)})
    return {"ok": ok, "builtin": "device_power", "device": device_name, "action": ctx["action"], "results": results}


# ---------------------------------------------------------------------
# Intent: scenario start/end ("Sentinel, start scenario security drill" /
# "Sentinel, end scenario")
# ---------------------------------------------------------------------

SCENARIO_START_PATTERN = re.compile(r"^(?:sentinel[,]?\s+)?start\s+scenario\s+(.+)$", re.IGNORECASE)
SCENARIO_END_PHRASES = {"end scenario", "stop scenario", "sentinel end scenario", "finish scenario"}


def _match_scenario(normalized, phrase):
    stripped = phrase.strip()
    m = SCENARIO_START_PATTERN.match(stripped)
    if m:
        return {"action": "start", "name": m.group(1).strip()}
    if normalized in SCENARIO_END_PHRASES:
        return {"action": "end"}
    return None


def _handle_scenario(phrase, output, ctx):
    from modules.scenario_ops import start_scenario, stop_scenario, get_active_scenario

    if ctx["action"] == "end":
        active = get_active_scenario()
        if not active:
            spoken = "No scenario is currently active."
            speak_result = _speak(spoken, output)
            ok = bool(speak_result.get("ok"))
            return {"ok": ok, "builtin": "scenario", "action": "end", "results": [{"type": "speak", "ok": ok, "phrase": spoken, "result": speak_result}]}
        stop_scenario(active["id"])
        spoken = f"Ending scenario {active['name']}."
        speak_result = _speak(spoken, output)
        ok = bool(speak_result.get("ok"))
        _log(f"Built-in end-scenario command ({output})", ok, {"scenario_id": active["id"]})
        return {"ok": ok, "builtin": "scenario", "action": "end", "results": [
            {"type": "scenario", "ok": True, "result": {"id": active["id"]}},
            {"type": "speak", "ok": ok, "phrase": spoken, "result": speak_result},
        ]}

    try:
        scenario = start_scenario({"name": ctx["name"]})
        spoken = f"Starting scenario {scenario['name']}."
        results_ok = True
    except ValueError as e:
        spoken = str(e)
        results_ok = False

    speak_result = _speak(spoken, output)
    ok = results_ok and bool(speak_result.get("ok"))
    _log(f"Built-in start-scenario command: {ctx['name']} ({output})", ok, {"name": ctx["name"]})
    return {"ok": ok, "builtin": "scenario", "action": "start", "results": [{"type": "speak", "ok": bool(speak_result.get("ok")), "phrase": spoken, "result": speak_result}]}


# ---------------------------------------------------------------------
# Intent: Hue scene by name ("Sentinel, set the scene to armed" /
# "activate alert scene" / "trigger critical scene"). The matcher itself
# validates the captured text against real scene names before claiming the
# phrase - "activate"/"trigger" are common enough verbs that a structural-
# only match could otherwise swallow phrases meant for a custom automation
# (e.g. one literally named "activate combat mode") and block it from ever
# reaching automation fuzzy-matching.
# ---------------------------------------------------------------------

SCENE_PATTERNS = [
    re.compile(r"^(?:sentinel[,]?\s+)?set\s+(?:the\s+)?scene\s+to\s+(.+)$", re.IGNORECASE),
    re.compile(r"^(?:sentinel[,]?\s+)?activate\s+(?:the\s+)?(.+?)(?:\s+scene)?$", re.IGNORECASE),
    re.compile(r"^(?:sentinel[,]?\s+)?trigger\s+(?:the\s+)?(.+?)(?:\s+scene)?$", re.IGNORECASE),
]


def _match_scene(normalized, phrase):
    stripped = phrase.strip()
    query = None
    for pat in SCENE_PATTERNS:
        m = pat.match(stripped)
        if m and m.group(1).strip():
            query = m.group(1).strip()
            break
    if not query:
        return None

    from modules.hue import load_scene_registry
    match = _best_string_match(query, [s["name"] for s in load_scene_registry()])
    return match[0] if match else None


def _handle_scene(phrase, output, scene_name):
    from modules.hue import set_scene
    result = set_scene(scene_name)
    ok_scene = bool(result.get("ok"))

    results = [{"type": "hue_scene", "ok": ok_scene, "result": result}]
    spoken = f"Scene set to {scene_name}." if ok_scene else "I couldn't reach the lights."
    speak_result = _speak(spoken, output)
    results.append({"type": "speak", "ok": bool(speak_result.get("ok")), "phrase": spoken, "result": speak_result})

    ok = ok_scene and bool(speak_result.get("ok"))
    _log(f"Built-in scene command: {scene_name} ({output})", ok, {"scene": scene_name})
    return {"ok": ok, "builtin": "scene", "scene": scene_name, "results": results}


# ---------------------------------------------------------------------
# Intent: VM start/stop ("Sentinel, start the Kali VM" / "stop
# metasploitable2"). Registered after the scenario intent so "start
# scenario X" is always resolved by the more specific scenario pattern
# first, never mis-caught here.
# ---------------------------------------------------------------------

VM_START_PATTERN = re.compile(r"^(?:sentinel[,]?\s+)?start\s+(?:the\s+)?(.+?)(?:\s+vm)?$", re.IGNORECASE)
VM_STOP_PATTERN = re.compile(r"^(?:sentinel[,]?\s+)?stop\s+(?:the\s+)?(.+?)(?:\s+vm)?$", re.IGNORECASE)


def _resolve_vm(query):
    from modules.proxmox import get_cluster_health
    vms = (get_cluster_health() or {}).get("vms") or []
    return _best_vm_match(query, vms)


def _best_vm_match(query, vms):
    query_n = _normalize(query)
    if not vms or not query_n:
        return None
    best, best_score = None, 0.0
    for vm in vms:
        name_n = _normalize(vm.get("name", ""))
        if not name_n:
            continue
        score = SequenceMatcher(None, query_n, name_n).ratio()
        if query_n in name_n or name_n in query_n:
            score = max(score, 0.85)
        if score > best_score:
            best, best_score = vm, score
    return (best, best_score) if best_score >= MATCH_THRESHOLD else None


def _match_vm_power(normalized, phrase):
    stripped = phrase.strip()
    m = VM_START_PATTERN.match(stripped)
    if m and m.group(1).strip():
        return {"action": "start", "query": m.group(1).strip()}
    m = VM_STOP_PATTERN.match(stripped)
    if m and m.group(1).strip():
        return {"action": "stop", "query": m.group(1).strip()}
    return None


def _handle_vm_power(phrase, output, ctx):
    from modules.proxmox import vm_action
    found = _resolve_vm(ctx["query"])
    if not found:
        return {"ok": False, "builtin": "vm_power", "error": f'No VM matching "{ctx["query"]}"', "results": []}
    vm, score = found
    action = "start" if ctx["action"] == "start" else "shutdown"
    try:
        result = vm_action(vm["node"], vm["vmid"], action)
        ok_vm = True
    except Exception as e:
        result = {"error": str(e)}
        ok_vm = False

    results = [{"type": "vm_power", "ok": ok_vm, "result": result}]
    verb = "Starting" if ctx["action"] == "start" else "Stopping"
    spoken = f"{verb} {vm['name']}." if ok_vm else f"Could not {ctx['action']} {vm['name']}."
    speak_result = _speak(spoken, output)
    results.append({"type": "speak", "ok": bool(speak_result.get("ok")), "phrase": spoken, "result": speak_result})

    ok = ok_vm and bool(speak_result.get("ok"))
    _log(f"Built-in VM power command: {ctx['action']} {vm['name']} ({output})", ok,
         {"vm": vm.get("name"), "vmid": vm.get("vmid"), "action": ctx["action"], "matched_score": round(score, 3)})
    return {"ok": ok, "builtin": "vm_power", "vm": vm["name"], "action": ctx["action"], "results": results}


# ---------------------------------------------------------------------
# Intent: help ("Sentinel, what can you do")
# ---------------------------------------------------------------------

HELP_PHRASES = {
    "help", "sentinel help", "what can you do", "what can you do?",
    "what commands do you know", "list commands", "what commands can i use",
}
HELP_TEXT = (
    "I can play music by song, artist, album, or playlist, control lights and scenes, "
    "report security, cluster, alert, and backup status, wake or shut down devices, "
    "start or stop virtual machines, start or end scenarios, and run any of your "
    "custom automations."
)


def _match_help(normalized, phrase):
    return True if normalized in HELP_PHRASES else None


def _handle_help(phrase, output, match):
    speak_result = _speak(HELP_TEXT, output)
    ok = bool(speak_result.get("ok"))
    _log(f"Built-in help command ({output})", ok)
    return {"ok": ok, "builtin": "help", "results": [{"type": "speak", "ok": ok, "phrase": HELP_TEXT, "result": speak_result}]}


# ---------------------------------------------------------------------
# Registry - order matters where patterns could otherwise overlap.
# ---------------------------------------------------------------------

INTENTS = [
    {"name": "help", "matcher": _match_help, "handler": _handle_help},
    {"name": "stop_music", "matcher": _match_stop, "handler": _handle_stop},
    {"name": "set_lights_brightness", "matcher": _match_brightness, "handler": _handle_brightness},
    {"name": "set_lights_color", "matcher": _match_color, "handler": _handle_color},
    {"name": "scene", "matcher": _match_scene, "handler": _handle_scene},
    {"name": "security_status", "matcher": _match_security_status, "handler": _handle_security_status},
    {"name": "cluster_status", "matcher": _match_cluster_status, "handler": _handle_cluster_status},
    {"name": "alerts", "matcher": _match_alerts, "handler": _handle_alerts},
    {"name": "backup_status", "matcher": _match_backup_status, "handler": _handle_backup_status},
    {"name": "device_power", "matcher": _match_device_power, "handler": _handle_device_power},
    {"name": "scenario", "matcher": _match_scenario, "handler": _handle_scenario},
    {"name": "vm_power", "matcher": _match_vm_power, "handler": _handle_vm_power},
    {"name": "play_by_artist", "matcher": _match_play_by_artist, "handler": _handle_play_by_artist},
    {"name": "play_music", "matcher": _match_play, "handler": _handle_play},
]


WAKE_PREFIX_PATTERN = re.compile(r"^\s*(?:hey[,.!]?\s+)?(?:sentinel[,.!]?\s+)?", re.IGNORECASE)


def _strip_wake_prefix(phrase):
    return WAKE_PREFIX_PATTERN.sub("", phrase, count=1)


def try_builtin_command(phrase, output="pi"):
    """Returns a result dict (matching run_automation()'s shape: ok/results)
    if phrase matches a registered intent, or None if it matches none - the
    caller should fall back to automation-trigger matching in that case."""
    # Strip a leading "hey"/"sentinel"/"hey sentinel" wake phrase once, here,
    # so every matcher below - regex-based or flat-phrase-set-based - sees
    # just the command itself regardless of how it was addressed. Every
    # individual pattern in this file only ever stripped a bare "sentinel "
    # prefix, so the natural "Hey, Sentinel, ..." phrasing silently matched
    # nothing at all, in every built-in intent, this whole time.
    phrase = _strip_wake_prefix(phrase.strip())
    normalized = _normalize(phrase)
    if not normalized:
        return None

    for intent in INTENTS:
        match = intent["matcher"](normalized, phrase)
        if match not in (None, False):
            return intent["handler"](phrase, output, match)
    return None
