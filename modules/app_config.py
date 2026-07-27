from pathlib import Path
import yaml
from modules.atomic import atomic_write_text

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config" / "local"


def _read_yaml(path, default=None):
    path = Path(path)
    if not path.exists():
        return default if default is not None else {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return default if default is not None else {}


def _write_yaml(path, data):
    atomic_write_text(Path(path), yaml.safe_dump(data or {}, sort_keys=False))
    return data


def get_yaml_config(name):
    return _read_yaml(CONFIG_DIR / f"{name}.yaml", {})


def save_yaml_config(name, data):
    return _write_yaml(CONFIG_DIR / f"{name}.yaml", data or {})


def get_all_config():
    return {
        "hue": get_yaml_config("hue"),
        "proxmox": get_yaml_config("proxmox"),
        "wazuh": get_yaml_config("wazuh"),
        "devices": get_yaml_config("devices"),
    }
