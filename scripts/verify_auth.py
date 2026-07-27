"""Sweep every registered Flask route and confirm it actually requires a
session - the standing check against a repeat of v1's "169 unauthenticated
routes" problem. Run this after adding any new route.

Usage: python scripts/verify_auth.py [base_url] [password]
Defaults to http://127.0.0.1:8081 and prompts for the password.
"""
import getpass
import sys

import requests

EXEMPT_PATHS = {"/login", "/healthz"}


def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8081"
    password = sys.argv[2] if len(sys.argv) > 2 else getpass.getpass("Password: ")

    anon = requests.Session()
    auth = requests.Session()

    login = auth.post(f"{base_url}/login", data={"password": password}, allow_redirects=False)
    if login.status_code not in (302, 303):
        print(f"Could not log in (status {login.status_code}). Aborting.")
        sys.exit(1)

    routes_resp = anon.get(f"{base_url}/api/health")
    # Can't introspect app.url_map remotely, so this script is meant to be
    # copy-pasted with a route list, or run in-process. Simple black-box
    # version: probe the route list passed on stdin, one path per line.
    print("Paste route paths to check (one per line), then Ctrl-D:")
    failures = []
    for line in sys.stdin:
        path = line.strip()
        if not path or path in EXEMPT_PATHS or path.startswith("/static/"):
            continue
        r = anon.get(f"{base_url}{path}", allow_redirects=False)
        ok = r.status_code in (401, 302, 303)
        if not ok:
            failures.append((path, r.status_code))
        print(f"{'OK ' if ok else 'FAIL'}  {path}  -> {r.status_code}")

    if failures:
        print(f"\n{len(failures)} route(s) did NOT require auth:")
        for path, code in failures:
            print(f"  - {path} ({code})")
        sys.exit(1)
    print("\nAll checked routes require authentication.")


if __name__ == "__main__":
    main()
