"""One-shot: set the Sentinel v2 login password.

Run this once before starting the app for the first time (or any time you
want to change the password). Never types the plaintext password into a
file - only its hash is stored.
"""
import getpass
import secrets
import sys
from pathlib import Path

import yaml
from werkzeug.security import generate_password_hash

AUTH_PATH = Path(__file__).resolve().parent.parent / "config" / "local" / "auth.yaml"


def main():
    AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if AUTH_PATH.exists():
        existing = yaml.safe_load(AUTH_PATH.read_text()) or {}

    username = input(f"Username [{existing.get('username', 'admin')}]: ").strip() or existing.get("username", "admin")
    password = getpass.getpass("New password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match. Nothing was written.")
        sys.exit(1)
    if len(password) < 8:
        print("Password should be at least 8 characters. Nothing was written.")
        sys.exit(1)

    secret_key = existing.get("flask_secret_key") or secrets.token_hex(32)

    AUTH_PATH.write_text(yaml.safe_dump({
        "username": username,
        "password_hash": generate_password_hash(password),
        "flask_secret_key": secret_key,
    }, sort_keys=False))

    print(f"Wrote {AUTH_PATH}")


if __name__ == "__main__":
    main()
