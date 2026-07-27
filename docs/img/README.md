# Screenshots

Drop screenshots here and uncomment the image block near the top of the
root `README.md`.

Suggested set, in the order that tells the story best:

| File | Page | What it should show |
|---|---|---|
| `mission-control.png` | `/mission-control` | The wallboard — topology, gauges, everything live at once. This is the one that sells it |
| `dashboard.png` | `/` | Mission status banner, device grid, activity timeline |
| `security.png` | `/security` | Wazuh agent health, threat level, vulnerability counts |
| `cluster.png` | `/cluster` | Multi-node telemetry, quorum state |
| `vms.png` | `/vms` | VM inventory with the action set |
| `login.png` | `/login` | Worth including — the auth gate is the headline of the rewrite |

## Before you screenshot

The UI renders real infrastructure. Check each image for:

- Real LAN IPs and MAC addresses (device cards, the network page, VM detail)
- Hostnames you'd rather not publish
- The WireGuard page — **never** screenshot a generated peer config or QR
  code; those are live credentials
- Wazuh agent names and IPs
- Anything in the activity log or scenario notes

Either censor them or populate a demo `config/local/devices.yaml` with
documentation-range addresses first.

Consistency tips: capture at a single window width (1440px works well), use
the same theme across all shots, and let the pages finish their first poll so
no indicator is stuck on `UNKNOWN`.
