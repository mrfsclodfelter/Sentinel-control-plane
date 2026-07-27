"""Small HTTP client for the Cerberus Core Pi relay service (port 5000).

This is a physical GPIO relay controller for Cerberus Heavy's power button -
separate from the voice/music Pi integration (cerberus-noc, SSH-based),
which is out of Stage 1 scope. This one is just plain HTTP and stays in.
"""
import requests
from modules.config import load_yaml


def _config():
    try:
        cfg = load_yaml("config/cerberus_core.yaml")
    except RuntimeError:
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "base_url": str(cfg.get("base_url", "http://192.0.2.50:5000")).rstrip("/"),
        "timeout_seconds": float(cfg.get("timeout_seconds", 1.5)),
        "display_name": str(cfg.get("display_name", "Cerberus Core")),
    }


def core_get_status():
    cfg = _config()
    if not cfg["enabled"]:
        return {"ok": False, "disabled": True, "name": cfg["display_name"]}
    try:
        r = requests.get(f'{cfg["base_url"]}/api/status', timeout=cfg["timeout_seconds"])
        r.raise_for_status()
        data = r.json()
        data["_core_url"] = cfg["base_url"]
        return data
    except Exception as e:
        return {"ok": False, "error": str(e), "name": cfg["display_name"], "_core_url": cfg["base_url"]}


def core_post(path):
    cfg = _config()
    if not cfg["enabled"]:
        return {"ok": False, "disabled": True}
    try:
        r = requests.post(f'{cfg["base_url"]}{path}', timeout=cfg["timeout_seconds"])
        try:
            data = r.json()
        except Exception:
            data = {"ok": r.ok, "text": r.text}
        data["_status_code"] = r.status_code
        return data
    except Exception as e:
        return {"ok": False, "error": str(e)}
