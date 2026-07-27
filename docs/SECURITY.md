# Security Model

Sentinel controls Proxmox hosts, so getting this wrong means someone on the
network can power off a lab. This document states what it does, what it
deliberately doesn't, and the risks accepted on purpose.

## Threat model

**In scope:** an unauthenticated party with access to the local network, or
to a device that once had access. Accidental credential exposure through the
repository or through the app's own responses.

**Out of scope:** an attacker with root on the Sentinel host — they already
have everything the app has. Nation-state adversaries. Physical access.

This is a single-operator home lab, not a multi-tenant product, and the
design reflects that. Where I made a lab-appropriate choice that wouldn't
survive a real deployment, I say so below.

## What the rewrite fixed

The predecessor to this codebase was reviewed and found to have:

| Finding | Fix |
|---|---|
| **169 routes with no authentication**, on an app that can shut down Proxmox hosts | One global `before_request` deny-by-default gate + a mechanical sweep script |
| **`GET /api/config/all` returned every stored credential as unauthenticated JSON** — Proxmox tokens, Wazuh password, Hue key | Behind the auth gate; config is never in a response body without a session |
| Config loader **silently fell back to `*.example.yaml`** when real config was missing | Loader fails loudly; no fallback path exists |
| A real password had been **committed inside a tracked example file** | Secrets moved to a wholly git-ignored *directory*; a startup scanner rejects real-looking values in examples |
| Four overlapping copies of device/topology data | One schema, one file, one key namespace |

## Controls

### Authentication

Single shared password. `werkzeug.security.generate_password_hash` /
`check_password_hash`. The hash and a random Flask secret key live in
`config/local/auth.yaml`, written by `scripts/set_password.py` via `getpass`.
Plaintext is never written to disk.

A single password is correct for one operator and wrong for a team. Multiple
accounts with distinct credentials would be the first thing to add if anyone
else needed access.

### Authorization gate

```python
@app.before_request
def _require_auth():
    ...  # deny unless explicitly exempt
```

Exempt: `/static/`, `/login`, `/healthz`, `/sw.js`.

Deny-by-default is the whole point. Per-route decorators fail silently when
forgotten — that's how 169 routes ended up unprotected. An exemption list
fails loudly: a new route 401s until you consciously exempt it.

`scripts/verify_auth.py` iterates `app.url_map` and asserts every non-exempt
rule rejects an anonymous request. Run it after adding routes, and in CI if
you wire one up.

### Session cookies

- `SESSION_COOKIE_HTTPONLY = True` — not readable from JavaScript.
- `SESSION_COOKIE_SAMESITE = "Lax"` — also gives free CSRF mitigation, since
  every mutating call in the frontend is a same-origin `fetch()`.
- 30-day lifetime, appropriate for a tool used from a phone over a VPN.

### Brute-force resistance

In-memory sliding window in `auth.py`: 5 failures in 15 minutes triggers a
60-second lockout, doubling per subsequent failure, capped at an hour.

State is per-process and resets on restart. Accepted: an attacker who can
restart the service already has root.

### Machine-to-machine auth

A Raspberry Pi endpoint posts voice and heartbeat data and cannot hold a
session. Rather than exempting those paths, it presents a narrow
single-purpose token on an enumerated allowlist of paths, compared with
`hmac.compare_digest` to avoid a timing side channel.

### Secret handling

- `config/local/` is git-ignored **as a directory**. There is no filename
  convention to violate.
- `config/examples/` holds placeholders only, and
  `scripts/check_config_examples.py` scans it for anything resembling a real
  secret. It runs **at application startup**, not only as a pre-commit hook —
  so a real token pasted into an example file stops the app from booting
  rather than waiting to be committed.
- Least-privilege Proxmox tokens: `PVEAuditor` (read-only) for endpoints that
  only need to be observed. Elevated rights are granted per endpoint,
  deliberately, never `Administrator`.
- Distinct credentials per application instance, so revoking one doesn't
  disturb anything else.

### Capability restriction by absence

The isolated malware-analysis host's guests are exposed through exactly one
read-only route. No start/stop/migrate route exists for them anywhere in
`app.py`.

Those VMs may contain live detonated malware and should only ever be reverted
from a clean snapshot. A disabled button is still a button; a route that
doesn't exist cannot be called.

### Input handling

- Automation and playlist actions validate against explicit allowlists
  (`ALLOWED_MUSIC_BEHAVIORS`, `ALLOWED_AFTER_TRACK`) and reject anything
  else — the action set is intentionally narrow, and there is no
  arbitrary-URL or arbitrary-command action to be abused as an SSRF or RCE
  primitive.
- File path handling uses `Path.is_relative_to()` against a base directory
  rather than string prefix comparison, which is defeatable with `..`.
- All persisted state goes through `atomic.py`, so a crash mid-write can't
  leave truncated JSON that later parses into something unintended.

### Logging hygiene

The activity log deliberately does **not** record raw transcribed voice
phrases — only the resolved intent. A log of everything said near a
microphone is a liability, and the useful signal (what the system did) is
preserved without it. Speech-to-text scratch audio is deleted after each use.

## Accepted risks

Stated plainly rather than papered over.

**1. Plain HTTP on the primary listener.**
Port 8081 is unencrypted. The session cookie is visible to anyone capturing
traffic on the LAN segment. The `:8443` listener uses a self-signed cert and
exists only to satisfy the browser's secure-context requirement for
microphone access — it is not a meaningful confidentiality control, since
nothing verifies the certificate.

*Correct fix:* terminate TLS with a real certificate in front of the app —
Caddy with a local CA, or a proper internal PKI. Not done here; the lab
network is small, physically controlled, and the exposure is understood.

**2. Single shared credential, no MFA, no audit trail per user.**
Appropriate for one operator; inadequate for shared access.

**3. Lockout state is in-memory.**
Resets on restart, and is per-process. Fine for a single-process deployment.

**4. Root privileges.**
The app runs as root for Wake-on-LAN broadcast, `wg set`, and relay GPIO. A
hardened deployment would drop these to a dedicated user with targeted
capabilities or a small privileged helper. The systemd unit includes
commented-out `User=`/`Group=` lines for deployments that don't need the
power-control paths.

**5. No rate limiting outside the login route.**
An authenticated session can poll API endpoints without limit. Acceptable
given the trust model; not acceptable if exposed beyond a trusted network.

## Reporting

This is a personal lab project, not a supported product. If you find
something interesting in it, open an issue — but please don't expect a
coordinated-disclosure process.
