import json
import os
import tempfile
from pathlib import Path


def atomic_write_text(path, text):
    """Write text to path without ever leaving a half-written file behind.

    Writes to a temp file in the same directory, then os.replace()'s it into
    place - the rename is atomic on POSIX, so a concurrent reader always sees
    either the old or the new content, never a partial write.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(path, data, indent=2):
    atomic_write_text(path, json.dumps(data, indent=indent))
