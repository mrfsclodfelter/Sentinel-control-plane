"""Scan config/examples/ for values that look like real secrets rather than
placeholders. Runs at app startup (see app.py) and can also be run by hand
or from a pre-commit hook.

This exists because v1's config/wazuh.example.yaml ended up with a real,
live password committed to git - the example file was hand-edited with a
real value instead of a placeholder, and nothing caught it. This check is
the automated backstop for that exact mistake.
"""
import re
import sys
from pathlib import Path

import yaml

EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "config" / "examples"

SECRET_KEY_PATTERN = re.compile(
    r"(password|token|secret|api[_-]?key|token_value|token_secret)", re.IGNORECASE
)

ALLOWED_PLACEHOLDER = re.compile(
    r"^(CHANGEME|REPLACE_?ME|TODO|)$|^PASTE_.*_HERE$", re.IGNORECASE
)


def _walk(data, path=""):
    if isinstance(data, dict):
        for k, v in data.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, data


def check_file(path):
    problems = []
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception as e:
        return [f"{path.name}: could not parse YAML - {e}"]

    for key_path, value in _walk(data):
        last_key = key_path.rsplit(".", 1)[-1].split("[")[0]
        if not SECRET_KEY_PATTERN.search(last_key):
            continue
        if value is None:
            continue
        value_str = str(value)
        if not ALLOWED_PLACEHOLDER.match(value_str):
            problems.append(f"{path.name}: '{key_path}' looks like a real value, not a placeholder: {value_str!r}")
    return problems


def check_all():
    problems = []
    if not EXAMPLE_DIR.exists():
        return problems
    for path in sorted(EXAMPLE_DIR.glob("*.example.yaml")):
        problems.extend(check_file(path))
    return problems


if __name__ == "__main__":
    problems = check_all()
    if problems:
        print("config/examples/ placeholder check FAILED:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("config/examples/ placeholder check passed.")
