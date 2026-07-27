import json
import time
import uuid
from pathlib import Path

from modules.atomic import atomic_write_json
from modules.music_output import list_tracks, set_command

STORE_PATH = Path("data/playlists.json")


def _load():
    if not STORE_PATH.exists():
        return []
    try:
        return json.loads(STORE_PATH.read_text())
    except Exception:
        return []


def _save(items):
    atomic_write_json(STORE_PATH, items)


def list_playlists():
    tracks_by_file = {t["file"]: t for t in list_tracks()}
    out = []
    for pl in _load():
        track_files = [f for f in pl.get("tracks", []) if f in tracks_by_file]
        out.append({
            "id": pl["id"],
            "name": pl["name"],
            "tracks": [tracks_by_file[f] for f in track_files],
            "track_count": len(track_files),
            "created": pl.get("created"),
            "updated": pl.get("updated"),
        })
    return out


def get_playlist(playlist_id):
    return next((p for p in list_playlists() if p["id"] == playlist_id), None)


def create_playlist(name):
    name = str(name or "").strip()
    if not name:
        raise ValueError("Playlist name is required")
    items = _load()
    record = {"id": str(uuid.uuid4())[:8], "name": name, "tracks": [], "created": time.time(), "updated": time.time()}
    items.append(record)
    _save(items)
    return get_playlist(record["id"])


def rename_playlist(playlist_id, name):
    name = str(name or "").strip()
    if not name:
        raise ValueError("Playlist name is required")
    items = _load()
    for p in items:
        if p["id"] == playlist_id:
            p["name"] = name
            p["updated"] = time.time()
    _save(items)
    return get_playlist(playlist_id)


def delete_playlist(playlist_id):
    items = [p for p in _load() if p["id"] != playlist_id]
    _save(items)
    return {"ok": True}


def set_playlist_tracks(playlist_id, track_files):
    """Replace the full ordered track list in one call - covers add, remove,
    and reorder without needing separate endpoints for each; the client
    always sends the new full order."""
    valid_files = {t["file"] for t in list_tracks()}
    items = _load()
    for p in items:
        if p["id"] == playlist_id:
            p["tracks"] = [f for f in (track_files or []) if f in valid_files]
            p["updated"] = time.time()
    _save(items)
    return get_playlist(playlist_id)


def play_playlist(playlist_id):
    playlist = get_playlist(playlist_id)
    if not playlist or not playlist["tracks"]:
        return {"ok": False, "error": "Playlist is empty or not found"}
    queue = [t["file"] for t in playlist["tracks"]]
    return {"ok": True, **set_command("play", file=queue[0], after_track="queue", queue=queue)}
