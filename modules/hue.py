import requests
import yaml
from pathlib import Path
from modules.config import load_yaml
from modules.atomic import atomic_write_text

BASE_DIR = Path(__file__).resolve().parent.parent


def load_hue_config():
    try:
        return load_yaml("config/hue.yaml").get("hue", {})
    except Exception:
        return {"enabled": False}


def _base_url(cfg):
    host = str(cfg.get("bridge_host", "")).strip()
    username = str(cfg.get("username", "")).strip()
    if not host or not username:
        raise RuntimeError("Hue bridge_host or username is not configured")
    return f"http://{host}/api/{username}"


def hue_enabled():
    cfg = load_hue_config()
    return bool(cfg.get("enabled")) and bool(cfg.get("bridge_host")) and bool(cfg.get("username"))


def hue_get(path):
    cfg = load_hue_config()
    r = requests.get(_base_url(cfg) + path, timeout=5)
    r.raise_for_status()
    return r.json()


def hue_put(path, payload):
    cfg = load_hue_config()
    r = requests.put(_base_url(cfg) + path, json=payload, timeout=5)
    r.raise_for_status()
    return r.json()


def hue_bridge_status():
    cfg = load_hue_config()
    out = {"ok": False, "enabled": bool(cfg.get("enabled")), "bridge_host": cfg.get("bridge_host"), "room_name": cfg.get("room_name"), "light_ids": cfg.get("light_ids", []), "groups": [], "lights": [], "error": None}
    if not hue_enabled():
        out["error"] = "Hue is disabled or not configured"
        return out
    try:
        config = hue_get("/config")
        groups = hue_get("/groups")
        lights = hue_get("/lights")
        out["ok"] = True
        out["bridge_name"] = config.get("name")
        out["groups"] = [{"id": gid, "name": g.get("name"), "type": g.get("type"), "lights": g.get("lights", [])} for gid, g in groups.items()]
        out["lights"] = [{"id": lid, "name": l.get("name"), "reachable": l.get("state", {}).get("reachable"), "on": l.get("state", {}).get("on")} for lid, l in lights.items()]
        return out
    except Exception as e:
        out["error"] = str(e)
        return out


def _target_light_ids():
    cfg = load_hue_config()
    ids = [str(x) for x in (cfg.get("light_ids") or [])]
    if ids:
        return ids
    room = str(cfg.get("room_name", "")).strip().lower()
    if room and hue_enabled():
        try:
            groups = hue_get("/groups")
            for gid, group in groups.items():
                if str(group.get("name", "")).strip().lower() == room:
                    return [str(x) for x in group.get("lights", [])]
        except Exception:
            pass
    return []


def _xy_for_color(color):
    if str(color or "").strip().startswith("#"):
        xy = _hex_to_xy(color)
        if xy:
            return xy
    palette = {"green": [0.17, 0.70], "blue": [0.16, 0.20], "cyan": [0.17, 0.34], "red": [0.67, 0.32], "orange": [0.56, 0.41], "yellow": [0.43, 0.50], "purple": [0.28, 0.12], "pink": [0.38, 0.17], "white": [0.3227, 0.3290]}
    return palette.get(str(color).lower(), palette["blue"])


def _hex_to_xy(hex_color):
    """Convert a #RRGGBB color into a Philips Hue xy value."""
    try:
        h = str(hex_color or "").strip().lstrip("#")
        if len(h) != 6:
            return None
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0

        def gamma(v):
            return ((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92

        r, g, b = gamma(r), gamma(g), gamma(b)
        x = r * 0.664511 + g * 0.154324 + b * 0.162028
        y = r * 0.283881 + g * 0.668433 + b * 0.047685
        z = r * 0.000088 + g * 0.072310 + b * 0.986039
        total = x + y + z
        if total <= 0:
            return None
        return [round(x / total, 4), round(y / total, 4)]
    except Exception:
        return None


def _transition_to_hue_units(value):
    try:
        value = int(value or 0)
        if value > 100:
            return max(0, round(value / 100))
        return max(0, value)
    except Exception:
        return 8


def scene_payload(color="blue", bri=180, transitiontime=8, effect=None, xy=None):
    payload = {"on": True, "bri": max(1, min(254, int(bri))), "transitiontime": int(transitiontime)}
    payload["xy"] = xy if xy else _xy_for_color(color)
    effect = str(effect or "static").lower()
    if effect in {"pulse", "alert"}:
        payload["alert"] = "select"
    elif effect == "critical":
        payload["alert"] = "lselect"
    elif effect == "colorloop":
        payload["effect"] = "colorloop"
    return payload


def set_lights(color="blue", bri=180, transitiontime=8, effect=None, xy=None):
    if not hue_enabled():
        return {"ok": False, "error": "Hue disabled or not configured", "results": []}
    ids = _target_light_ids()
    if not ids:
        return {"ok": False, "error": "No Hue light_ids configured and room_name did not resolve to lights", "results": []}
    payload = scene_payload(color, bri, transitiontime, effect, xy=xy)
    results = []
    for lid in ids:
        try:
            results.append({"id": lid, "result": hue_put(f"/lights/{lid}/state", payload)})
        except Exception as e:
            results.append({"id": lid, "error": str(e)})
    return {"ok": True, "light_ids": ids, "payload": payload, "results": results}


# --- Hue scene registry (config/hue_scene_registry.yaml - not a secret, tracked in git) ---

BUILTIN_SCENES = [
    {"name": "standby", "color": "#1f7aff", "brightness": 180, "transition": 700, "effect": "static"},
    {"name": "armed", "color": "#8c4dff", "brightness": 190, "transition": 500, "effect": "pulse"},
    {"name": "engaged", "color": "#ff2436", "brightness": 230, "transition": 250, "effect": "pulse"},
    {"name": "alert", "color": "#ffd24d", "brightness": 220, "transition": 250, "effect": "pulse"},
    {"name": "critical", "color": "#ff2436", "brightness": 254, "transition": 150, "effect": "pulse"},
    {"name": "complete", "color": "#35ff8a", "brightness": 210, "transition": 700, "effect": "static"},
    {"name": "backup", "color": "#00d4ff", "brightness": 180, "transition": 700, "effect": "static"},
]


def _scene_registry_path():
    return BASE_DIR / "config" / "hue_scene_registry.yaml"


def load_scene_registry():
    merged = {s["name"].lower(): dict(s) for s in BUILTIN_SCENES}
    data = _read_yaml_safe(_scene_registry_path())
    for s in data.get("scenes", []) or []:
        if isinstance(s, str):
            s = {"name": s}
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "")).strip()
        if not name:
            continue
        merged[name.lower()] = {
            "name": name,
            "color": s.get("color", "#1f7aff"),
            "brightness": int(s.get("brightness", 180) or 180),
            "transition": int(s.get("transition", 700) or 700),
            "effect": s.get("effect", "static"),
        }
    return list(merged.values())


def save_scene_registry(scenes):
    clean = []
    seen = set()
    for s in scenes or []:
        if isinstance(s, str):
            s = {"name": s}
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "")).strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        clean.append({
            "name": name,
            "color": s.get("color", "#1f7aff"),
            "brightness": int(s.get("brightness", 180) or 180),
            "transition": int(s.get("transition", 700) or 700),
            "effect": s.get("effect", "static"),
        })
    atomic_write_text(_scene_registry_path(), yaml.safe_dump({"scenes": clean}, sort_keys=False))
    return load_scene_registry()


def _read_yaml_safe(path):
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def _registry_scene(scene_name):
    wanted = str(scene_name or "").strip().lower()
    if not wanted:
        return None
    for scene in load_scene_registry():
        if str(scene.get("name", "")).strip().lower() == wanted:
            return scene
    return None


def _registry_scene_as_preset(scene):
    color = scene.get("color", "blue")
    xy = _hex_to_xy(color)
    return {
        "color": color,
        "bri": int(scene.get("brightness", scene.get("bri", 180)) or 180),
        "transitiontime": _transition_to_hue_units(scene.get("transition", scene.get("transitiontime", 700))),
        "effect": scene.get("effect", "static"),
        "xy": xy,
    }


def set_scene(scene):
    scene = str(scene or "standby")
    registry = _registry_scene(scene)
    if registry:
        return set_lights(**_registry_scene_as_preset(registry))

    preset = next((s for s in BUILTIN_SCENES if s["name"] == scene), None)
    if not preset:
        preset = next(s for s in BUILTIN_SCENES if s["name"] == "standby")
    return set_lights(**_registry_scene_as_preset(preset))
