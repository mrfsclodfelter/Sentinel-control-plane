"""WireGuard peer management for a wg0 tunnel already running on this host.

Additive-only by design: generating a peer applies it to the live interface
with `wg set` (touching nothing about any other peer's session) and appends
one block to wg0.conf (never rewriting the file), so a bug here cannot
corrupt or drop an existing, actively-used tunnel.

This module manages peers on a tunnel you set up yourself; it does not
create or configure the interface."""

import re
import subprocess
from pathlib import Path

WG_CONF = Path("/etc/wireguard/wg0.conf")
WG_DIR = Path("/etc/wireguard")
INTERFACE = "wg0"
# An existing, known-good client config, used only to read the current
# Endpoint=/DNS= values - so new peers automatically match whatever the
# reachable address currently is rather than one hardcoded at build time.
REFERENCE_CLIENT_CONF = WG_DIR / "reference-client.conf"
SUBNET_PREFIX = "10.50.0."
# What a generated peer is allowed to route over the tunnel. Deliberately
# narrow: the Sentinel host itself plus the tunnel's own gateway, so a peer
# config leaking doesn't hand out a route to the whole LAN. Set the first
# entry to your Sentinel host's LAN address.
SENTINEL_HOST_CIDR = "192.0.2.10/32"
CLIENT_ALLOWED_IPS = f"{SENTINEL_HOST_CIDR}, {SUBNET_PREFIX}1/32"


def _run(cmd, input_text=None, timeout=10):
    return subprocess.run(cmd, input=input_text, text=True, capture_output=True, timeout=timeout)


def _read_conf_text():
    return WG_CONF.read_text()


def _parse_peers(conf_text):
    """Small parser for our own wg0.conf convention: a '# Name' comment line
    immediately preceding each [Peer] block."""
    peers = []
    current_name = None
    current = None
    for line in conf_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            current_name = stripped.lstrip("#").strip()
            continue
        if stripped == "[Peer]":
            current = {"name": current_name or "Unnamed", "public_key": None, "allowed_ips": None}
            peers.append(current)
            current_name = None
            continue
        if current is not None:
            if stripped.startswith("PublicKey"):
                current["public_key"] = stripped.split("=", 1)[1].strip()
            elif stripped.startswith("AllowedIPs"):
                current["allowed_ips"] = stripped.split("=", 1)[1].strip()
    return peers


def _server_public_key():
    return _run(["wg", "show", INTERFACE, "public-key"]).stdout.strip()


def _live_status():
    """Map public_key -> live connection info from `wg show wg0 dump`."""
    result = _run(["wg", "show", INTERFACE, "dump"])
    status = {}
    lines = result.stdout.strip().splitlines()
    for line in lines[1:]:  # first line describes the interface itself
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        pubkey, _, endpoint, _allowed, handshake, rx, tx, _keepalive = parts[:8]
        handshake_ts = int(handshake) if handshake.isdigit() else 0
        status[pubkey] = {
            "endpoint": endpoint if endpoint != "(none)" else None,
            "latest_handshake": handshake_ts,
            "connected": handshake_ts > 0,
            "rx_bytes": int(rx) if rx.isdigit() else 0,
            "tx_bytes": int(tx) if tx.isdigit() else 0,
        }
    return status


def list_peers():
    peers = _parse_peers(_read_conf_text())
    status = _live_status()
    out = []
    for p in peers:
        s = status.get(p["public_key"], {})
        out.append({
            "name": p["name"],
            "public_key": p["public_key"],
            "allowed_ips": p["allowed_ips"],
            "connected": s.get("connected", False),
            "latest_handshake": s.get("latest_handshake", 0),
            "rx_bytes": s.get("rx_bytes", 0),
            "tx_bytes": s.get("tx_bytes", 0),
        })
    return out


def _next_free_ip():
    used = set()
    for p in _parse_peers(_read_conf_text()):
        ips = p.get("allowed_ips") or ""
        m = re.search(re.escape(SUBNET_PREFIX) + r"(\d+)", ips)
        if m:
            used.add(int(m.group(1)))
    for i in range(2, 255):
        if i not in used:
            return f"{SUBNET_PREFIX}{i}"
    raise RuntimeError("No free WireGuard addresses left in 10.50.0.0/24")


def _reference_endpoint_and_dns():
    if not REFERENCE_CLIENT_CONF.exists():
        raise RuntimeError("No reference client config found to read Endpoint/DNS from")
    endpoint, dns = None, None
    for line in REFERENCE_CLIENT_CONF.read_text().splitlines():
        line = line.strip()
        if line.startswith("Endpoint"):
            endpoint = line.split("=", 1)[1].strip()
        elif line.startswith("DNS"):
            dns = line.split("=", 1)[1].strip()
    if not endpoint:
        raise RuntimeError("Reference client config has no Endpoint= line")
    return endpoint, dns


def generate_peer(name):
    name = str(name or "").strip()
    if not re.match(r"^[A-Za-z0-9_ -]{1,32}$", name):
        raise ValueError("Name must be 1-32 letters/numbers/spaces/dashes/underscores")

    if name in {p["name"] for p in list_peers()}:
        raise ValueError(f'A peer named "{name}" already exists')

    privkey = _run(["wg", "genkey"]).stdout.strip()
    pubkey = _run(["wg", "pubkey"], input_text=privkey).stdout.strip()
    if not privkey or not pubkey:
        raise RuntimeError("Key generation failed")

    address = _next_free_ip()
    server_pubkey = _server_public_key()
    endpoint, dns = _reference_endpoint_and_dns()

    # Apply to the LIVE interface first - additive only, never touches any
    # existing peer's session. SaveConfig=false means this alone would not
    # survive a reboot, hence also persisting to wg0.conf below.
    apply = _run(["wg", "set", INTERFACE, "peer", pubkey, "allowed-ips", f"{address}/32"])
    if apply.returncode != 0:
        raise RuntimeError(f"Failed to apply peer to the live interface: {apply.stderr.strip()}")

    # Append-only write - never rewrites the file, so a bug here can't
    # touch the peers that already exist.
    block = f"\n# {name}\n[Peer]\nPublicKey = {pubkey}\nAllowedIPs = {address}/32\n"
    with WG_CONF.open("a") as f:
        f.write(block)

    # Public key kept on disk for reference. The private key is
    # deliberately NOT written to disk here - it only ever exists in the
    # one-time client config returned below, matching standard WireGuard
    # practice that a private key should live only on the device using it.
    (WG_DIR / f"{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'peer'}_public.key").write_text(pubkey + "\n")

    client_conf = (
        "[Interface]\n"
        f"PrivateKey = {privkey}\n"
        f"Address = {address}/32\n"
        + (f"DNS = {dns}\n" if dns else "")
        + "\n[Peer]\n"
        f"PublicKey = {server_pubkey}\n"
        f"Endpoint = {endpoint}\n"
        f"AllowedIPs = {CLIENT_ALLOWED_IPS}\n"
        "PersistentKeepalive = 25\n"
    )

    return {"ok": True, "name": name, "address": address, "public_key": pubkey, "config_text": client_conf}
