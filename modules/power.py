from modules.wol import send_magic_packet
from modules.relay import trigger_relay
from modules.logger import log
from modules.devices import load_devices
from modules.cerberus_core import core_post


def wake_device(key: str):
    devices = load_devices()
    if key not in devices:
        log(f"Unknown device: {key}")
        return
    dev = devices[key]
    if dev.get("enabled", True) is False:
        log(f"{dev['name']}: disabled")
        return
    method = dev.get("method")
    if method == "wol":
        try:
            send_magic_packet(dev.get("mac", ""))
            log(f"{dev['name']}: WoL sent")
        except Exception as e:
            log(f"{dev['name']}: WoL failed - {e}")
    elif method == "relay":
        trigger_relay(dev)
    elif method == "pi_relay":
        result = core_post("/api/heavy/power-on")
        if result.get("ok"):
            log(f"{dev['name']}: Cerberus Core relay pulse sent")
        else:
            log(f"{dev['name']}: Cerberus Core relay failed - {result.get('error')}")
    else:
        log(f"{dev['name']}: status only")


def set_device_power(key: str, action: str):
    """Wake or shut down a device by its devices.yaml key, respecting the
    exact same restrictions as the dashboard's /api/device/power route
    (disabled devices are refused, and shutdown only works for devices
    explicitly configured with shutdown_method=="proxmox" - e.g. Argus has
    none, deliberately, since it also hosts OPNsense). Used by the voice
    "wake up X" / "shut down X" commands so voice can't do anything the
    dashboard buttons couldn't already do."""
    from modules.activity_log import log_event

    devices = load_devices()
    dev = devices.get(key)
    if not dev:
        return {"ok": False, "error": f"Unknown device: {key}"}
    if dev.get("enabled", True) is False:
        return {"ok": False, "error": f"{dev['name']} is disabled/not configured.", "name": dev["name"]}

    if action == "wake":
        wake_device(key)
        log_event("power", "device_power", f"Wake sent to \"{dev['name']}\"", metadata={"device": key, "action": "wake"})
        return {"ok": True, "message": f"{dev['name']}: wake sent", "name": dev["name"]}

    if action == "shutdown":
        if dev.get("shutdown_method") != "proxmox":
            return {"ok": False, "error": f"{dev['name']} is not configured for shutdown.", "name": dev["name"]}
        from modules.proxmox import node_shutdown
        node = dev.get("node") or key
        try:
            result = node_shutdown(node)
            log(f"{dev['name']}: Proxmox shutdown requested")
            log_event("power", "device_power", f"Shutdown requested for \"{dev['name']}\"", severity="warning", metadata={"device": key, "action": "shutdown"})
            return {"ok": True, "message": f"{dev['name']}: shutdown requested", "result": result, "name": dev["name"]}
        except Exception as e:
            return {"ok": False, "error": str(e), "name": dev["name"]}

    return {"ok": False, "error": f"Unsupported action: {action}"}


def start_cerberus_net():
    devices = load_devices()
    log("Starting Cerberus Net")
    if "cerberus_heavy" in devices and devices["cerberus_heavy"].get("include_in_start", False):
        wake_device("cerberus_heavy")
        log("Cerberus Heavy startup trigger sent once only")
    for key, dev in devices.items():
        if key == "cerberus_heavy":
            continue
        if dev.get("include_in_start", False) and dev.get("enabled", True):
            wake_device(key)
    log("Cerberus Net startup command pass complete")
