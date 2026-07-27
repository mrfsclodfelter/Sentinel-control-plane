import json
from pathlib import Path
from modules.atomic import atomic_write_json

SETTINGS_PATH = Path("data/audio_settings.json")
DEFAULTS = {"voice_volume": 100, "media_volume": 100}


def get_audio_settings():
    if not SETTINGS_PATH.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(SETTINGS_PATH.read_text())
        return {**DEFAULTS, **{k: data.get(k, v) for k, v in DEFAULTS.items()}}
    except Exception:
        return dict(DEFAULTS)


def set_audio_settings(voice_volume=None, media_volume=None):
    current = get_audio_settings()
    if voice_volume is not None:
        current["voice_volume"] = max(0, min(100, int(voice_volume)))
    if media_volume is not None:
        current["media_volume"] = max(0, min(100, int(media_volume)))
    atomic_write_json(SETTINGS_PATH, current)
    return current
