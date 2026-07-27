from __future__ import annotations

import subprocess
import threading
import time
import wave
from pathlib import Path
from typing import Any, Dict


VOICE_ROOT = Path("/opt/sentinel-voice")
MODEL_PATH = VOICE_ROOT / "models" / "en_GB-northern_english_male-medium.onnx"
OUTPUT_DIR = VOICE_ROOT / "output"

PI_TARGET = "cerberus-noc"
PI_AUDIO_DEVICE = "plughw:2,0"
PI_REMOTE_WAV = "/tmp/sentinel-say.wav"

# Piper's ONNX model takes ~1.5s to load from disk - that cost used to be
# paid on every single TTS call because synthesis shelled out to a fresh
# `piper` process each time. Loading it once and keeping it warm in this
# long-running process cuts each subsequent call to well under 0.2s.
_VOICE_LOCK = threading.Lock()
_VOICE = None


def _get_voice():
    global _VOICE
    with _VOICE_LOCK:
        if _VOICE is None:
            from piper import PiperVoice
            _VOICE = PiperVoice.load(str(MODEL_PATH))
        return _VOICE


def _run(command: list[str], *, input_text: str | None = None, timeout: int = 30) -> Dict[str, Any]:
    started = time.time()

    proc = subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
    )

    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "seconds": round(time.time() - started, 3),
        "command": command,
    }


def synthesize_speech(text: str, output_name: str = "sentinel-say.wav") -> Dict[str, Any]:
    """Run Piper TTS and return a local wav path. Pure synthesis - no
    delivery to any output device. sentinel_say() (Pi delivery) and the
    browser push-to-talk route both build on this."""
    text = str(text or "").strip()

    if not text:
        return {
            "ok": False,
            "error": "No text provided",
        }

    if len(text) > 500:
        text = text[:500]

    if not MODEL_PATH.exists():
        return {
            "ok": False,
            "error": f"Piper model not found: {MODEL_PATH}",
        }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    local_wav = OUTPUT_DIR / output_name

    started = time.time()
    try:
        voice = _get_voice()
        with _VOICE_LOCK, wave.open(str(local_wav), "wb") as wf:
            voice.synthesize_wav(text, wf)
    except Exception as e:
        return {
            "ok": False,
            "stage": "synthesize",
            "text": text,
            "result": {"ok": False, "error": str(e)},
        }

    return {
        "ok": True,
        "stage": "complete",
        "text": text,
        "wav_path": str(local_wav),
        "synth": {"ok": True, "seconds": round(time.time() - started, 3)},
    }


def sentinel_say(text: str) -> Dict[str, Any]:
    synth_result = synthesize_speech(text)
    if not synth_result.get("ok"):
        return synth_result

    text = synth_result["text"]
    local_wav = Path(synth_result["wav_path"])
    synth = synth_result["synth"]

    copy = _run(
        [
            "scp",
            str(local_wav),
            f"{PI_TARGET}:{PI_REMOTE_WAV}",
        ],
        timeout=30,
    )

    if not copy["ok"]:
        return {
            "ok": False,
            "stage": "copy_to_pi",
            "text": text,
            "local_wav": str(local_wav),
            "result": copy,
        }

    from modules.audio_settings import get_audio_settings
    vol = get_audio_settings()["voice_volume"] / 100.0
    play = _run(
        [
            "ssh",
            PI_TARGET,
            f"ffmpeg -y -i {PI_REMOTE_WAV} -af volume={vol} -f wav - 2>/dev/null | aplay -D {PI_AUDIO_DEVICE} -",
        ],
        timeout=30,
    )

    return {
        "ok": play["ok"],
        "stage": "complete" if play["ok"] else "play_on_pi",
        "text": text,
        "local_wav": str(local_wav),
        "pi_target": PI_TARGET,
        "pi_audio_device": PI_AUDIO_DEVICE,
        "synth": synth,
        "copy": copy,
        "play": play,
    }


# ---------------------------------------------------------------------
# Pi music playback. Browser-triggered automations use modules.music_output
# (state the browser's own mini-player polls and plays via <audio> - no Pi
# involved at all). A voice command spoken into the Pi's own mic has no
# browser tab listening, so it needs a real delivery path of its own -
# mirrors sentinel_say()'s scp+ssh pattern, decoding through ffmpeg so any
# of the library's formats (mp3/ogg/wav/m4a) play the same way TTS does,
# through the same plughw:2,0 speaker.
# ---------------------------------------------------------------------

PI_REMOTE_MUSIC_MARKER = "sentinel-music-current"
# pkill -f matches against the full command line of every process - including
# the ssh session's own shell, which literally contains this marker string as
# part of the command we just sent it. Wrapping the first character in a
# bracket expression (a standard self-exclusion idiom) keeps the regex
# matching real player processes without matching pkill's own invocation.
_PI_MUSIC_KILL_PATTERN = f"[{PI_REMOTE_MUSIC_MARKER[0]}]{PI_REMOTE_MUSIC_MARKER[1:]}"


def play_music_on_pi(local_path: str | Path) -> Dict[str, Any]:
    local_path = Path(local_path)
    if not local_path.exists():
        return {"ok": False, "error": f"Track not found: {local_path}"}

    remote_path = f"/tmp/{PI_REMOTE_MUSIC_MARKER}{local_path.suffix}"

    # Kill anything already playing as its own separate ssh call - if the
    # pkill pattern and the remote file path (which also contains the same
    # marker string) ever land in one combined command, pkill -f matches
    # that outer invoking shell's own command line too and kills the ssh
    # session itself. Keeping them in separate round-trips avoids that.
    stop_music_on_pi()

    copy = _run(["scp", str(local_path), f"{PI_TARGET}:{remote_path}"], timeout=30)
    if not copy["ok"]:
        return {"ok": False, "stage": "copy_to_pi", "result": copy}

    from modules.audio_settings import get_audio_settings
    vol = get_audio_settings()["media_volume"] / 100.0

    # Fully detached (nohup + all fds redirected) so the ssh call returns
    # immediately instead of blocking for the length of the song.
    cmd = (
        f"nohup sh -c \"ffmpeg -y -i {remote_path} -af volume={vol} -f wav -ar 44100 -ac 2 - 2>/dev/null "
        f"| aplay -D {PI_AUDIO_DEVICE} -\" < /dev/null > /dev/null 2>&1 &"
    )
    play = _run(["ssh", PI_TARGET, cmd], timeout=15)

    return {
        "ok": play["ok"],
        "stage": "complete" if play["ok"] else "play_on_pi",
        "local_path": str(local_path),
        "pi_target": PI_TARGET,
        "copy": copy,
        "play": play,
    }


def stop_music_on_pi() -> Dict[str, Any]:
    result = _run(["ssh", PI_TARGET, f"pkill -f {_PI_MUSIC_KILL_PATTERN} 2>/dev/null; true"], timeout=15)
    return {"ok": result["ok"], "result": result}
