import re
import yaml
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOCAL_DIR = BASE / "config" / "local"
EXAMPLE_DIR = BASE / "config" / "examples"

_NAME_RE = re.compile(r"^config/([a-zA-Z0-9_\-]+)\.yaml$")


def _name_from_path(path):
    m = _NAME_RE.match(str(path))
    return m.group(1) if m else Path(path).stem


def load_yaml(path, required=True):
    """Load a real config value from config/local/.

    Accepts the same 'config/<name>.yaml' style path the old app used, so
    modules written against the old loader don't need to change. Never
    falls back to config/examples/ - a missing real config fails loudly,
    because silently running on placeholder values is how a fake credential
    ends up looking like a working one.

    required=False is for genuinely optional config (a module that has sane
    built-in defaults); it returns None instead of raising.
    """
    name = _name_from_path(path)
    p = LOCAL_DIR / f"{name}.yaml"
    if not p.exists():
        if not required:
            return None
        example = EXAMPLE_DIR / f"{name}.example.yaml"
        hint = f" Copy {example} to {p} and fill in real values." if example.exists() else ""
        raise RuntimeError(f"Missing required config: {p}.{hint}")
    with open(p, "r") as f:
        return yaml.safe_load(f) or {}
