# Sentinel

**A self-hosted control plane for a Proxmox-based cyber range.** One
authenticated web console for cluster health, VM lifecycle, Wazuh SIEM
telemetry, physical power control, remote access, and exercise logging.

Sentinel runs on a small always-on host *beside* the cluster it watches, so
that losing a cluster node doesn't take down the tool you'd use to diagnose
it.

<!-- Add screenshots here:
![Mission Control](docs/img/mission-control.png)
![Dashboard](docs/img/dashboard.png)
![Security](docs/img/security.png)
-->

---

## Why this exists

I built and run a home cyber range — a multi-node Proxmox cluster with an
OPNsense firewall, an Active Directory domain, deliberately vulnerable
targets, a Wazuh SIEM, and an isolated malware-analysis host. Operating it
meant juggling four Proxmox web UIs, the Wazuh dashboard, SSH sessions, and
a wall of bookmarks.

Sentinel collapses that into one console — and, more importantly, into one
place where the range's state is *observable* rather than something I have to
go assemble by hand every time.

### It started as a rewrite, and that's the interesting part

Version 1 worked, but a security review of it found:

- **169 routes with no authentication of any kind** — on an app that could
  shut down the Proxmox hosts underneath the entire lab.
- **`GET /api/config/all` returned every credential the app held** — Proxmox
  API tokens, the Wazuh password, the Hue bridge key — as unauthenticated
  JSON. Anyone on the LAN could `curl` the lot.
- A config loader that **silently fell back to `*.example.yaml`** when the
  real config was missing, which is precisely how a real password had ended
  up committed inside a tracked example file.
- Four overlapping copies of the same device/topology data, five generations
  of dead Hue-scene routes, and 18 JavaScript files no template referenced.

This repository is the rewrite. The security decisions in it are documented
in [docs/SECURITY.md](docs/SECURITY.md) — including the ones I'd do
differently at a larger scale, and the residual risks I accepted on purpose.

---

## What it does

| Area | Capability |
|---|---|
| **Cluster** | Multi-endpoint Proxmox API client; quorum and QDevice state; per-node CPU/RAM/uptime; storage and backup job status |
| **VMs** | Start/stop/reboot, snapshot, clone, migrate, backup, console — each queued through a shared operations queue with live task polling |
| **Security** | Wazuh manager + indexer integration: agent health, threat level, vulnerability counts, per-agent drill-down |
| **Power** | Wake-on-LAN, GPIO relay trigger via a Pi service, and Proxmox-native graceful shutdown — per device, driven by one unified device schema |
| **Mission Control** | Single-screen wallboard: animated topology, live gauges, click-through to any subsystem |
| **Remote access** | WireGuard peer generator with QR code; additive-only so it can't disturb existing tunnels |
| **Voice** | Local push-to-talk (browser mic → Whisper STT → intent registry → Piper TTS). No cloud speech services |
| **Exercises** | Scenario Ops: start/stop a range exercise, capture timestamped notes, export a Markdown after-action report |
| **Automations** | User-defined routines over a deliberately narrow, allowlisted action set |
| **Media** | Local music library with metadata/artwork extraction and playlists (it's a lab, morale matters) |

Everything is a first-class page in one navigation, and everything sits
behind a single login.

---

## Architecture

```
                    ┌──────────────────────────────┐
   Browser  ───────▶│  Flask app (app.py)          │
   Pi endpoint ────▶│  ── global before_request ───│  ← deny-by-default auth
                    │       auth gate              │
                    └───────────────┬──────────────┘
                                    │
       ┌──────────────┬─────────────┼─────────────┬──────────────┐
       ▼              ▼             ▼             ▼              ▼
   proxmox.py     wazuh.py       hue.py     wireguard.py   voice_commands.py
       │              │                                          │
       ▼              ▼                                          ▼
  Proxmox API    Wazuh API +                              Whisper / Piper
  (n endpoints)  Indexer                                  (local, offline)
```

Design notes worth calling out:

**The auth gate is global, not per-route.** A single `before_request` hook
denies everything except an explicit exemption list. Per-route decorators are
exactly the pattern that produced 169 unauthenticated routes in v1 — one
forgotten decorator is a hole. This way a new route is protected by default
and you have to *opt out* deliberately.

**Multi-endpoint Proxmox, with quorum kept honest.** Endpoints are a named
dict. The first is the primary cluster and owns quorum truth; additional
standalone hosts contribute node telemetry for display but are never counted
toward quorum. Adding a host to the dashboard can't accidentally turn an
odd-numbered cluster even.

**Read-only by construction where it matters.** The isolated malware-analysis
host is wired in as status-only — there are no VM action routes for its
guests at all, not merely hidden buttons. Those VMs should only ever be
reverted from a clean snapshot, so the capability to "restart" them doesn't
exist in the codebase.

**Atomic writes everywhere state is persisted.** `atomic.py` writes to a temp
file in the same directory and `os.replace()`s it in, so a concurrent reader
sees old or new content, never a half-written JSON file.

Full detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Security model

Short version:

- Single shared password (a one-operator home lab, not multi-tenant SaaS),
  hashed with `werkzeug.security`, never stored in plaintext.
- One global deny-by-default auth gate; `scripts/verify_auth.py` walks
  Flask's `url_map` and fails if any non-exempt route answers an
  unauthenticated request. Run it in CI or after every route you add.
- Sliding-window login lockout with exponential backoff.
- Secrets live in `config/local/`, git-ignored **as a directory** — not a
  filename convention that a stray `example` file can slip past.
- `scripts/check_config_examples.py` scans the tracked example files for
  real-looking secrets and **fails the app's startup**, not just a pre-commit
  hook. Pasting a real token into an example "just for a second" stops the
  app from booting.
- The Pi endpoint, which can't hold a session, gets a narrow single-purpose
  token checked with `hmac.compare_digest` rather than a blanket exemption.
- Least-privilege Proxmox tokens (`PVEAuditor`) for read-only endpoints.

Accepted, documented residual risks — and what I'd change for a real
deployment — are in [docs/SECURITY.md](docs/SECURITY.md). I'd rather write
those down than imply this is something it isn't.

---

## Stack

Python 3.11 · Flask · PyYAML · Requests · vanilla JS (no framework, no build
step) · Piper TTS · Whisper STT · systemd · Proxmox VE API · Wazuh API

No frontend build pipeline is a deliberate choice: this is an ops tool that
has to be debuggable at 2 a.m. from a phone over a VPN, and "view source"
being the whole story is worth more here than a component framework.

---

## Getting started

See [docs/INSTALL.md](docs/INSTALL.md). The short version:

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
mkdir -p config/local
for f in config/examples/*.example.yaml; do
  cp "$f" "config/local/$(basename "$f" .example.yaml).yaml"
done
# edit config/local/*.yaml
venv/bin/python scripts/set_password.py
venv/bin/python app.py          # binds 127.0.0.1:8081 by default
```

Confirm the auth gate holds before exposing it anywhere:

```bash
venv/bin/python scripts/verify_auth.py
```

---

## Repository notes

This is a sanitized public copy of an application that runs on real
infrastructure. Accordingly:

- `config/local/` is absent by design — all real credentials, tokens, TLS
  private keys, and the device inventory (LAN IPs and MACs) live there and
  are not published.
- Addresses in example configs and defaults use the
  [RFC 5737](https://datatracker.ietf.org/doc/html/rfc5737) documentation
  ranges (`192.0.2.0/24`), not real ones.
- The media library is excluded — it was full of copyrighted music.
- Host names (Cerberus, Osiris, Argus, Hades) are the lab's own
  mythology-themed naming and are kept, since they're woven through the code
  and are not sensitive on their own.

Documentation:
[Architecture](docs/ARCHITECTURE.md) ·
[Security](docs/SECURITY.md) ·
[Install](docs/INSTALL.md) ·
[Configuration](docs/CONFIGURATION.md)

## License

MIT — see [LICENSE](LICENSE).
