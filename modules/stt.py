from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Dict

from modules.automations import run_automation_by_phrase


STT_ROOT = Path("/opt/sentinel-stt/whisper.cpp")
WHISPER_BIN = STT_ROOT / "build" / "bin" / "whisper-cli"
WHISPER_MODEL = STT_ROOT / "models" / "ggml-tiny.en.bin"
WORK_DIR = Path("/tmp/sentinel-stt")


def _run(command: list[str], timeout: int = 60) -> Dict[str, Any]:
    started = time.time()

    proc = subprocess.run(
        command,
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


def _clean_transcript(text: str) -> str:
    text = str(text or "").strip()
    text = text.replace("[BLANK_AUDIO]", "").strip()
    text = " ".join(text.split())

    while text and text[-1] in ".!?":
        text = text[:-1].strip()

    return text


def _display_transcript(text: str) -> str:
    cleaned = _clean_transcript(text)

    if cleaned.lower().startswith("sentinel"):
        return "Sentinel" + cleaned[8:]

    return cleaned


def transcribe_audio_file(source_wav: str | Path) -> Dict[str, Any]:
    source_wav = Path(source_wav)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    converted = WORK_DIR / "command-16k.wav"
    output_base = WORK_DIR / "command"
    output_txt = WORK_DIR / "command.txt"

    # converted/output_txt are scratch copies of your actual spoken audio and
    # its transcript - always removed on the way out (success or failure) so
    # nothing outlives a single request. No voice command retention, ever.
    try:
        if not WHISPER_BIN.exists():
            return {
                "ok": False,
                "error": f"Whisper binary not found: {WHISPER_BIN}",
            }

        if not WHISPER_MODEL.exists():
            return {
                "ok": False,
                "error": f"Whisper model not found: {WHISPER_MODEL}",
            }

        convert = _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source_wav),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(converted),
            ],
            timeout=45,
        )

        if not convert["ok"]:
            return {
                "ok": False,
                "stage": "convert",
                "convert": convert,
            }

        whisper = _run(
            [
                str(WHISPER_BIN),
                "-m",
                str(WHISPER_MODEL),
                "-f",
                str(converted),
                "-nt",
                "-otxt",
                "-of",
                str(output_base),
            ],
            timeout=90,
        )

        if not whisper["ok"]:
            return {
                "ok": False,
                "stage": "transcribe",
                "convert": convert,
                "whisper": whisper,
            }

        transcript = output_txt.read_text(errors="replace") if output_txt.exists() else ""
        cleaned = _clean_transcript(transcript)
        display = _display_transcript(cleaned)

        return {
            "ok": bool(cleaned),
            "stage": "complete",
            "transcript": cleaned,
            "display_transcript": display,
            "convert": convert,
            "whisper": whisper,
        }
    finally:
        for scratch in (converted, output_txt):
            try:
                scratch.unlink(missing_ok=True)
            except OSError:
                pass


def process_voice_command_file(source_wav: str | Path, output: str = "pi") -> Dict[str, Any]:
    transcription = transcribe_audio_file(source_wav)

    if not transcription.get("ok"):
        return {
            "ok": False,
            "stage": "transcription_failed",
            "transcription": transcription,
        }

    phrase = transcription.get("transcript", "")

    from modules.voice_commands import try_builtin_command
    automation = try_builtin_command(phrase, output=output)
    if automation is None:
        automation = run_automation_by_phrase(phrase, output=output)

    return {
        "ok": bool(automation.get("ok")),
        "stage": "complete",
        "phrase": phrase,
        "display_phrase": transcription.get("display_transcript", phrase),
        "transcription": transcription,
        "automation": automation,
    }


# ---------------------------------------------------------------------
# Sentinel Pi microphone listener helper (manual "push to talk" path -
# Osiris SSHes to the Pi, records there, pulls the file back). Separate
# from the Pi's own always-on wake-word loop, which posts audio to us.
# ---------------------------------------------------------------------

PI_TARGET = "cerberus-noc"
PI_MIC_DEVICE = "plughw:3,0"
PI_REMOTE_COMMAND_WAV = "/tmp/sentinel-command.wav"
LOCAL_PI_COMMAND_WAV = WORK_DIR / "pi-command.wav"


def record_pi_voice_command(duration: int = 4) -> Dict[str, Any]:
    duration = int(duration or 4)
    duration = max(2, min(duration, 10))

    WORK_DIR.mkdir(parents=True, exist_ok=True)

    record = _run(
        [
            "ssh",
            PI_TARGET,
            f"aplay -q -D plughw:2,0 /tmp/sentinel-ready.wav 2>/dev/null || true; arecord -D {PI_MIC_DEVICE} -d {duration} -f cd {PI_REMOTE_COMMAND_WAV}",
        ],
        timeout=duration + 15,
    )

    if not record["ok"]:
        return {
            "ok": False,
            "stage": "record_on_pi",
            "record": record,
        }

    copy = _run(
        [
            "scp",
            f"{PI_TARGET}:{PI_REMOTE_COMMAND_WAV}",
            str(LOCAL_PI_COMMAND_WAV),
        ],
        timeout=30,
    )

    # Remove the Pi's own copy of the recording regardless of whether the
    # scp above succeeded - it's spoken audio sitting on a second machine
    # and shouldn't outlive this request either.
    _run(["ssh", PI_TARGET, f"rm -f {PI_REMOTE_COMMAND_WAV}"], timeout=10)

    if not copy["ok"]:
        return {
            "ok": False,
            "stage": "copy_from_pi",
            "record": record,
            "copy": copy,
        }

    try:
        processed = process_voice_command_file(LOCAL_PI_COMMAND_WAV)
    finally:
        try:
            LOCAL_PI_COMMAND_WAV.unlink(missing_ok=True)
        except OSError:
            pass

    return {
        "ok": bool(processed.get("ok")),
        "stage": "complete",
        "duration": duration,
        "record": record,
        "copy": copy,
        "result": processed,
    }
