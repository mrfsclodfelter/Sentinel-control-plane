import hmac
import time
import threading
import yaml
from pathlib import Path
from werkzeug.security import check_password_hash

AUTH_PATH = Path(__file__).resolve().parent.parent / "config" / "local" / "auth.yaml"

_LOCK = threading.Lock()
_FAILURES = {}  # ip -> [timestamps of recent failures]

WINDOW_SECONDS = 15 * 60
MAX_FAILURES = 5
BASE_LOCKOUT_SECONDS = 60


def _load_auth_config():
    if not AUTH_PATH.exists():
        raise RuntimeError(
            f"Missing {AUTH_PATH}. Run scripts/set_password.py to create it before starting the app."
        )
    with open(AUTH_PATH, "r") as f:
        return yaml.safe_load(f) or {}


def get_flask_secret_key():
    return _load_auth_config()["flask_secret_key"]


def _client_state(ip):
    now = time.time()
    events = [t for t in _FAILURES.get(ip, []) if now - t < WINDOW_SECONDS]
    _FAILURES[ip] = events
    return events


def is_locked_out(ip):
    with _LOCK:
        events = _client_state(ip)
        if len(events) < MAX_FAILURES:
            return False, 0
        # Exponential backoff keyed off how many failures beyond the threshold.
        overage = len(events) - MAX_FAILURES
        lockout = min(BASE_LOCKOUT_SECONDS * (2 ** overage), 3600)
        elapsed = time.time() - events[-1]
        remaining = lockout - elapsed
        if remaining <= 0:
            return False, 0
        return True, round(remaining)


def record_failure(ip):
    with _LOCK:
        events = _client_state(ip)
        events.append(time.time())
        _FAILURES[ip] = events


def record_success(ip):
    with _LOCK:
        _FAILURES.pop(ip, None)


def verify_password(password):
    cfg = _load_auth_config()
    return check_password_hash(cfg["password_hash"], password or "")


def verify_pi_token(token):
    """Constant-time check for the shared secret the Pi endpoint sends on
    its voice/heartbeat calls - those can't do a session login, so they get
    a narrow, single-purpose credential instead of a blanket auth exemption."""
    cfg = _load_auth_config()
    expected = cfg.get("pi_token")
    if not expected or not token:
        return False
    return hmac.compare_digest(str(expected), str(token))
