# Installation and Operation

Sentinel is designed to run on a small always-on Linux host that sits
*beside* your virtualization cluster rather than on it — so that losing a
cluster node doesn't take the thing you use to inspect the cluster with it.

Reference deployment: a low-power mini PC running Debian/Ubuntu, on the same
management network as the Proxmox hosts it watches.

## Requirements

- Python 3.11+
- A Proxmox VE cluster or standalone host with API access
- Optional: Wazuh manager + indexer, Philips Hue bridge, WireGuard (`wg0`)

## First-time setup

```bash
git clone https://github.com/<you>/sentinel-control-plane.git
cd sentinel-control-plane

python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### Configuration

Every real value lives in `config/local/`, which is git-ignored **as a
directory**. Copy each example and fill it in:

```bash
mkdir -p config/local
for f in config/examples/*.example.yaml; do
  name=$(basename "$f" .example.yaml)
  cp "$f" "config/local/$name.yaml"
done
```

Then edit `config/local/*.yaml`. See [CONFIGURATION.md](CONFIGURATION.md) for
what each file does and which are optional.

### Set the login password

Never hand-edit `config/local/auth.yaml`. Run:

```bash
venv/bin/python scripts/set_password.py
```

This prompts via `getpass`, writes a `werkzeug` password hash, and generates
a random Flask secret key. Plaintext passwords are never written to disk.

### Verify your config hygiene

```bash
venv/bin/python scripts/check_config_examples.py
```

This scans `config/examples/` for anything that looks like a real secret and
fails if it finds one. It also runs automatically at app startup — so if you
ever paste a real token into an example file "just for a second," the app
refuses to boot rather than letting it drift into a commit.

## Running

**Bind to localhost first and confirm auth works before exposing it.**

```bash
venv/bin/python app.py    # binds 127.0.0.1:8081 by default
```

Reach it from your workstation over an SSH tunnel:

```bash
ssh -L 8081:127.0.0.1:8081 user@your-sentinel-host
```

then open <http://127.0.0.1:8081/>.

Verify the auth gate is actually closed before going further:

```bash
venv/bin/python scripts/verify_auth.py
```

This walks Flask's `url_map` and asserts that every route outside the
explicit exemption list rejects an unauthenticated request. Run it again
after adding any route.

Only once that passes should you change the bind address in `app.py`'s
`__main__` block to expose it on the LAN.

## systemd

```bash
sudo cp systemd/sentinel.service /etc/systemd/system/
# edit WorkingDirectory / ExecStart to match your install path and user
sudo systemctl daemon-reload
sudo systemctl enable --now sentinel
```

## HTTPS listener (optional, port 8443)

A second listener runs on `:8443` with a self-signed certificate. This is
**not** meant as real transport security — it exists because browsers only
expose the microphone and other powerful Web APIs on a "secure context," so
push-to-talk simply does not work over plain HTTP on a non-localhost origin.

Generate a cert:

```bash
mkdir -p config/local/tls
openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
  -keyout config/local/tls/key.pem -out config/local/tls/cert.pem \
  -subj "/CN=sentinel.local" \
  -addext "subjectAltName=IP:<your-host-ip>,DNS:<your-hostname>,DNS:localhost,IP:127.0.0.1"
```

You'll get a one-time browser warning; that's expected for a self-signed
cert. The plain HTTP listener on `:8081` is unchanged and remains what
scripts and the Pi endpoint use.

If you want genuine transport security, terminate TLS with a real
certificate in front of the app (Caddy with a local CA works well) rather
than relying on this listener.

## Upgrading

```bash
git pull
venv/bin/pip install -r requirements.txt
sudo systemctl restart sentinel
```

`config/local/` and `data/` are untracked, so they survive upgrades
untouched.
