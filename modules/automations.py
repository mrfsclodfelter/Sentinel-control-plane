import json
import random
import re
import time
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from modules.atomic import atomic_write_json
from modules.hue import set_scene, load_scene_registry
from modules.music_output import set_command as set_music_command

STORE_PATH = Path("data/automations.json")

ALLOWED_MUSIC_BEHAVIORS = {"none", "play", "stop"}
ALLOWED_AFTER_TRACK = {"stop", "playlist", "shuffle"}
PHRASE_MATCH_THRESHOLD = 0.6


def _load():
    if not STORE_PATH.exists():
        return []
    try:
        return json.loads(STORE_PATH.read_text())
    except Exception:
        return []


def _save(items):
    atomic_write_json(STORE_PATH, items)


def list_automations():
    return _load()


def get_automation(automation_id):
    return next((a for a in _load() if a["id"] == automation_id), None)


def _lines(value):
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def create_or_update_automation(payload, existing_id=None):
    payload = payload or {}
    items = _load()

    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Automation name is required")

    music_behavior = str(payload.get("music_behavior") or "none").strip()
    if music_behavior not in ALLOWED_MUSIC_BEHAVIORS:
        raise ValueError(f"Unsupported music behavior: {music_behavior}")

    after_track = str(payload.get("after_track") or "stop").strip()
    if after_track not in ALLOWED_AFTER_TRACK:
        raise ValueError(f"Unsupported after-track behavior: {after_track}")

    automation_id = existing_id or str(uuid.uuid4())[:8]
    existing = next((a for a in items if a["id"] == automation_id), {})

    record = {
        "id": automation_id,
        "name": name,
        "category": str(payload.get("category") or "custom").strip() or "custom",
        "description": str(payload.get("description") or "").strip(),
        "enabled": bool(payload.get("enabled", existing.get("enabled", True))),

        "voice_triggers": _lines(payload.get("voice_triggers")),
        "natural_phrases": _lines(payload.get("natural_phrases")),
        "spoken_response": str(payload.get("spoken_response") or "").strip(),
        "alternate_responses": _lines(payload.get("alternate_responses")),

        "hue_scene": str(payload.get("hue_scene") or "").strip(),
        "music_behavior": music_behavior,
        "music_track": str(payload.get("music_track") or "").strip(),
        "after_track": after_track,

        "created": existing.get("created", time.time()),
        "updated": time.time(),
    }
    items = [a for a in items if a["id"] != automation_id]
    items.append(record)
    _save(items)
    return record


def delete_automation(automation_id):
    items = [a for a in _load() if a["id"] != automation_id]
    _save(items)
    return {"ok": True}


def set_automation_enabled(automation_id, enabled):
    items = _load()
    found = None
    for a in items:
        if a["id"] == automation_id:
            a["enabled"] = bool(enabled)
            found = a
    _save(items)
    return found


def run_automation(automation_id, trigger_source="manual", output="pi"):
    """output picks where a spoken response is delivered: "pi" (default -
    scp+ssh to the NOC Pi's speaker, matching the existing wake-word/manual
    behavior) or "browser" (synthesize only, return the wav path so the
    caller can hand audio bytes back to whichever browser tab triggered
    it - push-to-talk responds through the same device that was spoken
    into, not the Pi)."""
    automation = get_automation(automation_id)
    if not automation:
        return {"ok": False, "error": "Automation not found"}
    if not automation.get("enabled", True):
        return {"ok": False, "error": "Automation is disabled"}

    results = []

    if automation.get("hue_scene"):
        result = set_scene(automation["hue_scene"])
        results.append({"type": "hue_scene", "ok": bool(result.get("ok")), "result": result})

    behavior = automation.get("music_behavior", "none")
    if trigger_source == "voice" and output == "pi":
        # A command spoken into the Pi's own mic has no browser tab
        # listening for browser playback state, so it needs real delivery
        # to the Pi's own speaker - same as the spoken response gets.
        from modules.voice import play_music_on_pi, stop_music_on_pi
        from modules.music_output import get_track_path
        if behavior == "stop":
            result = stop_music_on_pi()
            results.append({"type": "music_stop", "ok": bool(result.get("ok")), "result": result})
        elif behavior == "play" and automation.get("music_track"):
            track_path = get_track_path(automation["music_track"])
            if track_path:
                result = play_music_on_pi(track_path)
                results.append({"type": "music_play", "ok": bool(result.get("ok")), "result": result})
            else:
                results.append({"type": "music_play", "ok": False, "result": {"error": "Track not found"}})
    else:
        if behavior == "stop":
            result = set_music_command("stop")
            results.append({"type": "music_stop", "ok": True, "result": result})
        elif behavior == "play" and automation.get("music_track"):
            result = set_music_command(
                "play",
                file=automation["music_track"],
                after_track=automation.get("after_track", "stop"),
            )
            results.append({"type": "music_play", "ok": True, "result": result})

    pool = ([automation["spoken_response"]] if automation.get("spoken_response") else []) + (automation.get("alternate_responses") or [])
    if pool:
        phrase = random.choice(pool)
        if output == "browser":
            from modules.voice import synthesize_speech  # deferred: keeps voice.py optional if Piper isn't installed
            result = synthesize_speech(phrase, output_name=f"ptt-{uuid.uuid4().hex[:8]}.wav")
        else:
            from modules.voice import sentinel_say
            result = sentinel_say(phrase)
        results.append({"type": "speak", "ok": bool(result.get("ok")), "phrase": phrase, "result": result})

    ok = all(r.get("ok") for r in results) if results else True

    from modules.activity_log import log_event
    did = [r["type"] for r in results]
    log_event(
        "automations", "automation_run",
        f"Automation \"{automation['name']}\" ran ({trigger_source}){' - ' + ', '.join(did) if did else ''}",
        severity="info" if ok else "warning",
        metadata={"automation_id": automation_id, "trigger_source": trigger_source, "results": did},
    )

    return {"ok": ok, "automation": automation, "results": results}


def _normalize_phrase(text):
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


def _phrase_similarity(a, b):
    a, b = _normalize_phrase(a), _normalize_phrase(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    a_words, b_words = set(a.split()), set(b.split())
    if a_words and b_words:
        overlap = len(a_words & b_words) / max(len(a_words), len(b_words))
        ratio = max(ratio, overlap)
    return ratio


def run_automation_by_phrase(phrase, output="pi"):
    """Match a transcribed voice command against every enabled automation's
    voice_triggers and natural_phrases (both are just alternate ways of
    saying the same command - matched identically) and run the best match.
    Used by the Pi's wake-word listener (output="pi") and the browser
    push-to-talk path (output="browser")."""
    normalized = _normalize_phrase(phrase)
    if not normalized:
        return {"ok": False, "error": "Empty phrase"}

    best_automation, best_score = None, 0.0
    for automation in _load():
        if not automation.get("enabled", True):
            continue
        triggers = list(automation.get("voice_triggers", [])) + list(automation.get("natural_phrases", []))
        for trigger in triggers:
            if _normalize_phrase(trigger) in normalized or normalized in _normalize_phrase(trigger):
                best_automation, best_score = automation, 1.0
                break
            score = _phrase_similarity(normalized, trigger)
            if score > best_score:
                best_automation, best_score = automation, score
        if best_score >= 1.0:
            break

    if not best_automation or best_score < PHRASE_MATCH_THRESHOLD:
        return {"ok": False, "error": "No matching automation", "phrase": phrase, "best_score": round(best_score, 3)}

    result = run_automation(best_automation["id"], trigger_source="voice", output=output)
    result["matched_score"] = round(best_score, 3)
    return result
