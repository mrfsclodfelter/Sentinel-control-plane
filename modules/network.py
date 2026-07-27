import subprocess
import socket
import time

from modules.config import load_yaml

# Fallbacks used only when config/local/network.yaml is absent. The gateway
# default is deliberately a documentation-range address, not a real one -
# set your own in config/local/network.yaml.
DEFAULTS = {
    "gateway": "192.0.2.1",
    "internet_probe": "1.1.1.1",
    "dns_probe": "example.com",
}


def _settings():
    try:
        cfg = load_yaml("network", required=False) or {}
    except Exception:
        cfg = {}
    return {**DEFAULTS, **{k: v for k, v in cfg.items() if v}}


def _ping(host, timeout="1"):
    result = subprocess.run(
        ["ping", "-c", "1", "-W", timeout, host],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return result.returncode == 0

def check_network_health():
    cfg = _settings()
    router_ip = cfg["gateway"]
    internet_ip = cfg["internet_probe"]
    dns_name = cfg["dns_probe"]
    router = _ping(router_ip)
    internet = _ping(internet_ip)
    try:
        socket.gethostbyname(dns_name)
        dns = True
    except Exception:
        dns = False
    return {
        "router": router,
        "internet": internet,
        "dns": dns,
        # Surfaced so the UI can label each check with what it actually
        # probed, instead of repeating the addresses in the template.
        "targets": cfg,
        "checked_at": int(time.time())
    }
