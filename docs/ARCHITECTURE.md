# Architecture

## Shape of the thing

Sentinel is a single Flask process. There is no task queue, no message
broker, no database — state is JSON files written atomically, and everything
else is fetched live from the APIs it fronts.

That is a deliberate ceiling. This is an operations console for one operator
and roughly a dozen machines. Introducing Postgres and Celery here would add
two more services that can fail in a system whose entire purpose is telling
you what's failing.

```
sentinel/
  app.py              routing, the global auth gate, config bootstrap checks
  modules/            one module per integration or concern
  templates/          Jinja2, server-rendered
  static/js/          one file per page, vanilla, no build step
  config/examples/    tracked; placeholders only; validated at startup
  config/local/       git-ignored as a directory; every real value
  data/               git-ignored; runtime JSON state
  scripts/            operational scripts (password, auth sweep, config scan)
  systemd/            unit file
```

## Request lifecycle

1. `@app.before_request` → `_require_auth()`. Deny-by-default: unless the
   path matches an explicit exemption (`/static/`, `/login`, `/healthz`,
   `/sw.js`) or presents a valid Pi token on one of the narrowly enumerated
   `PI_TOKEN_PATHS`, an unauthenticated request gets a 401 (for `/api/`) or a
   redirect to `/login` (for pages).
2. Route handler calls into a `modules/` function.
3. That module talks to an external API or reads/writes a JSON file under
   `data/` via `atomic.py`.
4. Templates render server-side; page-specific JS polls `/api/*` endpoints
   for live updates.

## Modules

| Module | Responsibility |
|---|---|
| `auth.py` | Password verification, sliding-window lockout, Pi-token check |
| `config.py` | Loads `config/local/*.yaml`. Fails loudly on missing config; `required=False` for genuinely optional files |
| `devices.py` | The single device schema — one file, one key namespace |
| `proxmox.py` | Multi-endpoint Proxmox API client, cluster health aggregation |
| `wazuh.py` | Wazuh manager + indexer queries: agents, threat level, vulnerabilities |
| `power.py` / `wol.py` / `relay.py` | The three power methods behind one interface |
| `operations_queue.py` | Queues long-running Proxmox tasks, polls for completion |
| `status.py` | Device reachability with a cached/background-refresh pattern |
| `network.py` | Gateway / internet / DNS reachability checks |
| `hue.py` | Philips Hue bridge client and scene math |
| `wireguard.py` | Additive-only WireGuard peer management |
| `voice*.py`, `stt.py` | Local speech: Whisper in, intent registry, Piper out |
| `automations.py` | User-defined routines over an allowlisted action set |
| `scenario_ops.py` | Range exercise capture and after-action report generation |
| `atomic.py` | Crash-safe file writes |
| `activity_log.py` | Append-only event log surfaced in the UI |

## Decisions worth explaining

### The auth gate is global

```python
@app.before_request
def _require_auth():
    if request.path.startswith(EXEMPT_PREFIXES) or request.path in EXEMPT_EXACT:
        return
    if request.path in PI_TOKEN_PATHS and auth.verify_pi_token(...):
        return
    if not session.get("authenticated"):
        ...
```

The predecessor used per-route `@login_required` decorators and ended up with
169 routes that had none. The failure mode of a decorator is silent: you add
a route, forget the decorator, and nothing tells you. The failure mode of an
exemption list is loud: you add a route, it 401s, and you notice immediately.

`scripts/verify_auth.py` enforces this mechanically by iterating
`app.url_map` and asserting every non-exempt rule rejects an anonymous
request.

### Config: two directories, not a filename convention

The original repo gitignored `config/*.yaml` and tracked `*.example.yaml`.
A real Wazuh password ended up committed inside a tracked example file,
because the rule lived in a person's head at edit time.

Now the boundary is structural:

- `config/examples/` — always tracked, placeholders only.
- `config/local/` — the entire directory is git-ignored. No exceptions
  inside it, so there is nothing to get wrong.

And `scripts/check_config_examples.py` runs **at application startup**, not
just as a hook, so an example file containing a real-looking secret prevents
the app from booting.

The loader also refuses to fall back to examples. The old one did, with the
comment "fall back to example only to keep UI alive" — which meant the app
would happily run against placeholder values and look healthy.

### Multi-endpoint Proxmox without corrupting quorum

`config/local/proxmox.yaml` holds a dict of named endpoints. The first is
the primary cluster: its `/cluster/status` drives quorum, QDevice state, and
node membership.

Every other endpoint is a standalone host. `_collect_cluster_health()` loops
over the non-primary reachable endpoints and merges *only their own node
telemetry* into the display list. They never enter the quorum calculation.

This matters physically: the range's malware-analysis host is deliberately
kept out of the Proxmox cluster so corosync heartbeat and shared-storage
paths never reach the isolated detonation network. Sentinel can show you its
CPU and RAM without that isolation decision being quietly undone in software.

### Status-only by absence, not by hiding

The malware-analysis host's guests (a REMnux box and a Windows analysis VM)
are surfaced through one read-only endpoint, `/api/hades/guests`. There is no
corresponding action route anywhere in `app.py`.

That is the point. Those VMs may hold detonated malware and should only ever
be restored from a clean snapshot. A hidden button is a button; a missing
route is a missing capability.

### Atomic writes

Every JSON write goes through `atomic.py`: temp file in the same directory,
then `os.replace()`. On POSIX the rename is atomic, so a reader polling
`data/automations.json` while it's being rewritten sees the old file or the
new one, never a truncated one.

The predecessor wrote JSON in place with no locking, which is also why
Sentinel runs against its own fresh `data/` directory rather than sharing
one.

### No frontend build step

Vanilla JS, one file per page, `<script src>`. No bundler, no transpiler, no
`node_modules`.

An ops console gets used exactly when things are broken — often from a phone,
over a VPN, at an unreasonable hour. Being able to read the shipped source in
devtools and understand it is worth more than the ergonomics a framework
would buy. The tradeoff is real (no components, some repetition across page
scripts), and at a larger scale I'd make it differently.

## Data flow: a representative request

`GET /api/summary` (the dashboard's 5-second poll):

1. Auth gate confirms the session.
2. `proxmox.get_cluster_health()` — cached; a stale cache triggers a
   background refresh and returns last-known state rather than blocking.
3. `wazuh.get_summary()` — agent health, threat level, vulnerability counts.
4. `network.check_network_health()` — three pings and a DNS resolve.
5. `status.get_all_statuses()` — per-device reachability from the cache.
6. Assembled into a single JSON payload so the page makes one request, not
   six.
