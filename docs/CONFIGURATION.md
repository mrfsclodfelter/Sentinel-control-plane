# Configuration Reference

All real values live in `config/local/`. That directory is git-ignored in its
entirety — not by a filename pattern, but as a directory, so there is nothing
to get subtly wrong.

Templates live in `config/examples/` and contain placeholders only. They are
validated at application startup by `scripts/check_config_examples.py`; if a
real-looking secret ends up in one, the app refuses to boot.

| File | Required | Purpose |
|---|:---:|---|
| `auth.yaml` | ✅ | Login credential hash, Flask secret key, Pi token |
| `proxmox.yaml` | ✅ | Proxmox API endpoints and tokens |
| `devices.yaml` | ✅ | The device inventory and power methods |
| `wazuh.yaml` | — | Wazuh manager + indexer connection |
| `hue.yaml` | — | Philips Hue bridge |
| `network.yaml` | — | Reachability probe targets |
| `cerberus_core.yaml` | — | Pi GPIO relay service URL |
| `tls/cert.pem`, `tls/key.pem` | — | Enables the `:8443` secure-context listener |

Missing a **required** file raises a clear `RuntimeError` naming the file and
the example to copy. Missing an optional one just disables that feature.

---

## `auth.yaml`

**Do not hand-edit.** Run:

```bash
venv/bin/python scripts/set_password.py
```

It prompts with `getpass`, writes a `werkzeug` password hash, and generates a
random Flask secret key.

```yaml
username: "operator"
password_hash: "scrypt:32768:8:1$..."   # generated
flask_secret_key: "..."                 # generated
pi_token: "..."                         # optional; only if you run the Pi endpoint
```

`pi_token` is a shared secret for the Raspberry Pi voice/heartbeat endpoint,
which cannot hold a browser session. It grants access to an enumerated
allowlist of paths only. Omit it if you aren't running that endpoint.

---

## `proxmox.yaml`

A dict of named endpoints. **The first is the primary cluster** — its quorum
and node membership drive Mission Control. Every other endpoint is treated as
a standalone host: its node telemetry is displayed, but it never counts toward
quorum.

```yaml
proxmox:
  primary-cluster:
    host: "192.0.2.10:8006"
    user: "<api-user>@pve"
    token_name: "<token-name>"
    token_value: "..."
  standalone-host:
    host: "192.0.2.11:8006"
    user: "<api-user>@pve"
    token_name: "<token-name>"
    token_value: "..."

verify_ssl: false
```

Create least-privilege tokens rather than reusing root:

```bash
pveum user add <api-user>@pve
pveum aclmod / -user <api-user>@pve -role PVEAuditor    # read-only
pveum user token add <api-user>@pve <token-name> --privsep 0
```

`PVEAuditor` covers everything Sentinel needs to *observe* a host. Grant more
only on the endpoints where you actually want Sentinel to act.

---

## `devices.yaml`

One schema for the whole app — the status grid, the power controls, and the
topology view all read from this single file.

```yaml
devices:
  example_node:
    name: Example Node          # display name
    ip: 192.0.2.40
    mac: "AA:BB:CC:DD:EE:FF"    # required for wake_method: wol
    role: Proxmox Node          # free-text subtitle
    method: wol                 # wol | relay | pi_relay | status_only
    relay_gpio: 0               # GPIO pin, for relay/pi_relay
    relay_enabled: false
    node: example-node          # Proxmox node name, for shutdown_method: proxmox
    wake_method: wol
    shutdown_method: proxmox    # proxmox | none
    always_on: false            # true = never offer power controls
    managed_power: true
    include_in_start: true      # include in the "start everything" sequence
    enabled: true
```

Notes:

- `status_only` devices render a status card with no action buttons. Use it
  for anything that must never be driven from the UI.
- `always_on: true` suppresses power controls for hosts that shouldn't be
  cycled — the app host itself, the firewall.
- The key (`example_node`) is the internal identifier. It is used by the
  topology map in `static/js/topology-status.js`, so keep them in sync if you
  customize the diagram.

---

## `wazuh.yaml` *(optional)*

Two separate services: the manager API (agents, health) and the indexer
(vulnerability data). They frequently use different credentials.

```yaml
wazuh:
  host: 192.0.2.20
  port: 55000
  verify_ssl: false
  username: "..."
  password: "..."

indexer:
  host: 192.0.2.20
  port: 9200
  verify_ssl: false
  username: "..."
  password: "..."
```

If your Wazuh manager sits behind a firewall on another segment, point `host`
at whatever address is actually reachable from the Sentinel host — a NAT'd
WAN address is fine. A stale value here is the usual cause of the Security
page showing `UNKNOWN`.

---

## `hue.yaml` *(optional)*

```yaml
hue:
  enabled: false
  bridge_host: "192.0.2.30"
  username: "..."      # the bridge "username" is a bearer credential
  room_name: "The Lab"
  light_ids: []        # empty = all lights in the room
```

Pair a fresh bridge username via the link-button flow — press the physical
button on the bridge, then `POST` to `http://<bridge>/api` with a new
`devicetype` string within the pairing window. Don't reuse an existing app's
credential; they can't be scoped or individually revoked easily.

---

## `network.yaml` *(optional)*

Targets for the three reachability checks on the dashboard.

```yaml
gateway: "192.0.2.1"          # your LAN gateway
internet_probe: "1.1.1.1"     # always-up external IP
dns_probe: "example.com"      # hostname to resolve
```

Defaults are documentation-range addresses, so the checks are meaningless
until you set real ones.

---

## `cerberus_core.yaml` *(optional)*

A small HTTP service on a Raspberry Pi that physically presses a power button
via a GPIO relay — for hosts that don't support Wake-on-LAN.

```yaml
enabled: true
base_url: "http://192.0.2.50:5000"
timeout_seconds: 1.5
display_name: "Relay Controller"
```

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `SENTINEL_BIND` | `127.0.0.1` | Bind address. Set to `0.0.0.0` **only after** `scripts/verify_auth.py` passes |
| `SENTINEL_PORT` | `8081` | HTTP port |
| `SENTINEL_TLS_PORT` | `8443` | HTTPS port, active only when a cert exists |

The localhost default is intentional: a fresh clone should never be
LAN-reachable before a password has been set.
