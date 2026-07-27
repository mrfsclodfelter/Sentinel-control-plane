from modules.config import load_yaml


def load_devices():
    """Unified device/topology schema (replaces v1's devices.yaml +
    infrastructure.yaml split). One file: config/local/devices.yaml.
    """
    return load_yaml("config/devices.yaml")["devices"]


def get_device(key):
    return load_devices().get(key)
