import json
import random
import re
import time
from pathlib import Path
from modules.atomic import atomic_write_json

MUSIC_DIR = Path("static/music")
COMMAND_PATH = Path("data/music_command.json")
ALLOWED_EXT = {".mp3", ".ogg", ".wav", ".m4a"}

_TRACK_NUMBER_PREFIX = re.compile(r"^\d+[\.\-_\s]+")

# Keyed by file name -> (mtime, metadata dict). Avoids re-parsing ID3/Vorbis
# tags on every list_tracks() call - it's hit often (voice matching, mini
# player dropdown, page loads). mtime in the key means replacing a file
# invalidates its own cache entry automatically.
_METADATA_CACHE = {}


def _display_name(stem):
    stem = _TRACK_NUMBER_PREFIX.sub("", stem)
    return stem.replace("_", " ").replace("-", " ").strip()


def _extract_artwork_bytes(path):
    """Raw (non-easy) tag access, needed because embedded pictures aren't
    exposed through mutagen's easy=True interface. Returns (mime, data) or
    (None, None)."""
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(str(path))
        if audio is None:
            return None, None
        if audio.tags:
            for key in audio.tags.keys():
                if str(key).startswith("APIC"):
                    pic = audio.tags[key]
                    return (pic.mime or "image/jpeg"), pic.data
        if hasattr(audio, "pictures") and audio.pictures:
            pic = audio.pictures[0]
            return (pic.mime or "image/jpeg"), pic.data
        if "covr" in (audio or {}):
            covr = audio["covr"]
            if covr:
                return "image/jpeg", bytes(covr[0])
    except Exception:
        pass
    return None, None


def _read_metadata(path):
    mtime = path.stat().st_mtime
    cached = _METADATA_CACHE.get(path.name)
    if cached and cached[0] == mtime:
        return cached[1]

    title = artist = album = track_number = None
    duration = None
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(str(path), easy=True)
        if audio is not None:
            if audio.info and getattr(audio.info, "length", None):
                duration = round(audio.info.length)
            if audio.tags:
                title = (audio.tags.get("title") or [None])[0]
                artist = (audio.tags.get("artist") or [None])[0]
                album = (audio.tags.get("album") or [None])[0]
                raw_track = (audio.tags.get("tracknumber") or [None])[0]
                if raw_track:
                    try:
                        track_number = int(str(raw_track).split("/")[0])
                    except ValueError:
                        track_number = None
    except Exception:
        pass

    mime, _ = _extract_artwork_bytes(path)

    meta = {"title": title, "artist": artist, "album": album, "duration": duration,
            "track_number": track_number, "has_artwork": mime is not None}
    _METADATA_CACHE[path.name] = (mtime, meta)
    return meta


def list_tracks():
    if not MUSIC_DIR.exists():
        return []
    tracks = []
    for p in MUSIC_DIR.iterdir():
        if not p.is_file() or p.suffix.lower() not in ALLOWED_EXT:
            continue
        meta = _read_metadata(p)
        fallback_name = _display_name(p.stem)
        tracks.append({
            "file": p.name,
            "name": meta["title"] or fallback_name,
            "title": meta["title"] or fallback_name,
            "artist": meta["artist"] or "",
            "album": meta["album"] or "",
            "duration": meta["duration"],
            "track_number": meta["track_number"],
            "has_artwork": meta["has_artwork"],
        })
    return sorted(tracks, key=lambda t: t["name"].lower())


COVERS_DIR = Path("data/music_covers")


def get_artwork_path(file_name):
    """Extract and cache embedded cover art. Returns (path, mime) or
    (None, None) if the track has no embedded picture. Cached outside
    static/ (not directly web-reachable) keyed by source mtime, so a
    replaced file's stale art can't be served."""
    src = _safe_track_path(file_name)
    if not src:
        return None, None

    mime, data = _extract_artwork_bytes(src)
    if not data:
        return None, None

    ext = ".png" if "png" in (mime or "") else ".jpg"
    cache_path = COVERS_DIR / f"{src.stem}{ext}"
    if not (cache_path.exists() and cache_path.stat().st_mtime >= src.stat().st_mtime):
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)
    return cache_path, (mime or "image/jpeg")


def _safe_track_path(file_name):
    file_name = str(file_name or "").strip()
    if not file_name:
        return None
    base = MUSIC_DIR.resolve()
    path = (base / file_name).resolve()
    if not path.is_relative_to(base):
        return None
    if not path.exists() or not path.is_file():
        return None
    return path


def get_track_path(file_name):
    """Public wrapper around the path-traversal-safe track lookup, for
    callers outside this module (e.g. Pi music delivery) that need the real
    file path rather than just setting browser playback state."""
    return _safe_track_path(file_name)


def delete_track(file_name):
    path = _safe_track_path(file_name)
    if not path:
        return {"ok": False, "error": "Track not found"}
    path.unlink()
    return {"ok": True, "tracks": list_tracks()}


def get_command():
    if not COMMAND_PATH.exists():
        return {"id": 0, "action": "none"}
    try:
        return json.loads(COMMAND_PATH.read_text())
    except Exception:
        return {"id": 0, "action": "none"}


def set_command(action, file=None, loop=False, after_track="stop", queue=None):
    command = {
        "id": int(time.time() * 1000),
        "action": action,
        "file": file,
        "loop": bool(loop),
        # What the browser should do when this track finishes naturally:
        # stop | playlist (advance alphabetically through the whole library)
        # | shuffle | queue (advance through a specific ordered playlist,
        # see `queue` below)
        "after_track": after_track if after_track in {"stop", "playlist", "shuffle", "queue"} else "stop",
        # Ordered list of file names, only meaningful when after_track=="queue"
        "queue": queue,
        "time": time.time(),
    }
    atomic_write_json(COMMAND_PATH, command)
    return command


def shuffle_command():
    tracks = list_tracks()
    if not tracks:
        return {"ok": False, "error": "No tracks available"}
    chosen = random.choice(tracks)
    return {"ok": True, **set_command("play", file=chosen["file"], after_track="shuffle")}


def next_track_after(current_file):
    """Return the track that follows current_file - walks the active
    playlist queue if one is set (after_track=="queue"), otherwise falls
    back to whole-library alphabetical order ('playlist' after-track mode).
    Returns None at the end of a queue (stop) or if the library is empty."""
    current_cmd = get_command()
    if current_cmd.get("after_track") == "queue" and current_cmd.get("queue"):
        queue = current_cmd["queue"]
        try:
            idx = queue.index(current_file)
        except ValueError:
            idx = -1
        if idx + 1 >= len(queue):
            return None
        next_file = queue[idx + 1]
        tracks_by_file = {t["file"]: t for t in list_tracks()}
        return tracks_by_file.get(next_file)

    tracks = list_tracks()
    if not tracks:
        return None
    names = [t["file"] for t in tracks]
    try:
        idx = names.index(current_file)
    except ValueError:
        idx = -1
    return tracks[(idx + 1) % len(tracks)]
