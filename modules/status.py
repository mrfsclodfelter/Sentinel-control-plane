import subprocess
import time
import threading
from modules.devices import load_devices

_DEVICE_CACHE = None
_DEVICE_CACHE_TS = 0.0
_DEVICE_CACHE_TTL = 10.0
_DEVICE_REFRESHING = False
_DEVICE_LOCK = threading.Lock()


def is_online(ip: str) -> bool:
    for _ in range(2):
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        if result.returncode == 0:
            return True
    return False


def _collect_device_statuses():
    devices = load_devices()
    statuses = {}
    for key, dev in devices.items():
        if dev.get("enabled", True) is False:
            statuses[key] = "disabled"
        elif not dev.get("ip"):
            # Devices behind a NAT/VLAN boundary (e.g. Wazuh, post-migration)
            # aren't directly pingable from here by design - status_only
            # devices without an IP are reported via their own integration
            # page instead of a raw ping.
            statuses[key] = "unknown"
        elif is_online(dev["ip"]):
            statuses[key] = "online"
        else:
            statuses[key] = "offline"
    return devices, statuses


def _refresh_device_cache():
    global _DEVICE_CACHE, _DEVICE_CACHE_TS, _DEVICE_REFRESHING
    try:
        data = _collect_device_statuses()
        with _DEVICE_LOCK:
            _DEVICE_CACHE = data
            _DEVICE_CACHE_TS = time.time()
    finally:
        with _DEVICE_LOCK:
            _DEVICE_REFRESHING = False


def _start_device_refresh():
    global _DEVICE_REFRESHING
    with _DEVICE_LOCK:
        if _DEVICE_REFRESHING:
            return
        _DEVICE_REFRESHING = True
    t = threading.Thread(target=_refresh_device_cache, daemon=True)
    t.start()


def get_device_statuses():
    """Return cached device status immediately when possible.

    This prevents page loads from blocking on offline devices. If cached data is
    stale, a background refresh starts and the last known Osiris-owned state is
    returned to the UI.
    """
    global _DEVICE_CACHE, _DEVICE_CACHE_TS
    now = time.time()
    with _DEVICE_LOCK:
        cache = _DEVICE_CACHE
        age = now - _DEVICE_CACHE_TS

    if cache is None:
        _refresh_device_cache()
        with _DEVICE_LOCK:
            return _DEVICE_CACHE

    if age > _DEVICE_CACHE_TTL:
        _start_device_refresh()

    return cache
