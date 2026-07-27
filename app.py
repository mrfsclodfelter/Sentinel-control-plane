import sys
import base64
from pathlib import Path
from flask import Flask, render_template, redirect, jsonify, request, session, url_for, Response, send_file

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts.check_config_examples import check_all as _check_config_examples

_example_problems = _check_config_examples()
if _example_problems:
    raise RuntimeError(
        "config/examples/ contains real-looking secret values, refusing to start:\n"
        + "\n".join(f"  - {p}" for p in _example_problems)
    )

from modules import auth
from modules.devices import load_devices
from modules.status import get_device_statuses
from modules.logger import get_logs, log
from modules.power import wake_device, start_cerberus_net
from modules.operations_queue import add_operation, update_operation, list_operations
from modules.hue import (
    hue_bridge_status, set_lights, set_scene,
    load_scene_registry, save_scene_registry,
)
from modules.app_config import get_all_config, get_yaml_config, save_yaml_config
from modules.proxmox import (
    get_cluster_health, get_backup_info, get_proxmox_endpoints, get_active_proxmox_endpoint,
    vm_action, vm_backup, vm_snapshot, vm_monitor_command, vm_migrate, vm_clone,
    vm_console_proxy, proxmox_vm_ui_url, node_shutdown, get_hades_guests,
)
from modules.network import check_network_health
from modules.wazuh import get_wazuh_summary, get_agent_security
from modules.voice import sentinel_say
from modules.stt import transcribe_audio_file, process_voice_command_file, record_pi_voice_command
from modules.voice_listener import listener_status, listener_control
from modules.activity_log import log_event, get_recent_events, maybe_snapshot_wazuh, get_events_by_type
from modules.scenario_ops import (
    list_scenarios, get_scenario, get_active_scenario, start_scenario,
    stop_scenario, add_note, render_report,
)
from modules.assessment import build_assessment
import tempfile
from modules.music_output import list_tracks, delete_track, get_command as get_music_command, set_command as set_music_command, shuffle_command, next_track_after
from modules.playlists import (
    list_playlists, get_playlist, create_playlist, rename_playlist,
    delete_playlist, set_playlist_tracks, play_playlist,
)
from modules.wireguard import list_peers as wg_list_peers, generate_peer as wg_generate_peer
from modules.automations import (
    list_automations, get_automation, create_or_update_automation,
    delete_automation, set_automation_enabled, run_automation,
)
from werkzeug.utils import secure_filename

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent

app.config["SECRET_KEY"] = auth.get_flask_secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30  # 30 days


# ---------------------------------------------------------------------------
# Auth gate. Deny-by-default: every route needs a session unless explicitly
# exempted below. This is deliberate - v1 ended up with 169 unauthenticated
# routes because auth was never wired in at all, not because a decorator was
# forgotten on any one of them. A single global gate can't have that failure
# mode: a new route is protected automatically, with no extra code required.
# ---------------------------------------------------------------------------
EXEMPT_PREFIXES = ("/static/",)
# /sw.js must stay exempt: browsers fetch it directly (bypassing whatever
# service worker is currently active) both on first registration and on
# periodic background update checks, and reject a redirected response for a
# service-worker script outright - if this ever required a session, a fresh
# visit or an expired cookie would silently break PWA install/update instead
# of just falling back to a normal login redirect like every other route.
EXEMPT_EXACT = {"/login", "/healthz", "/sw.js"}

# The Pi endpoint can't do a browser session login, so its handful of routes
# accept a narrow, single-purpose shared-secret header instead - never a
# blanket auth exemption. Everything else still needs a real session.
PI_TOKEN_PATHS = {"/api/voice/transcribe-audio", "/api/voice/command-audio", "/api/endpoints/heartbeat"}


@app.before_request
def _require_auth():
    if request.path.startswith(EXEMPT_PREFIXES) or request.path in EXEMPT_EXACT:
        return
    if request.path in PI_TOKEN_PATHS and auth.verify_pi_token(request.headers.get("X-Sentinel-Token")):
        return
    if not session.get("authenticated"):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return redirect(url_for("login", next=request.path))


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.route("/sw.js")
def service_worker():
    # Served from the root (not /static/sw.js) so its default scope covers
    # the whole app - browsers cap a worker's scope to its own directory
    # unless the server sends a Service-Worker-Allowed header, and
    # root-serving sidesteps needing that entirely.
    resp = Response((BASE_DIR / "static" / "sw.js").read_text(), mimetype="application/javascript")
    # Never let a browser or intermediary cache this past its own SW-update
    # check - a stale cached copy of a broken worker is exactly how this
    # class of bug outlives its own fix.
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("authenticated"):
            return redirect("/")
        return render_template("login.html", error=None)

    ip = request.remote_addr or "unknown"
    locked, remaining = auth.is_locked_out(ip)
    if locked:
        return render_template("login.html", error=f"Too many attempts. Try again in {remaining}s."), 429

    password = request.form.get("password", "")
    if auth.verify_password(password):
        auth.record_success(ip)
        session.clear()
        session["authenticated"] = True
        session.permanent = True
        next_path = request.args.get("next") or "/"
        if not next_path.startswith("/"):
            next_path = "/"
        return redirect(next_path)

    auth.record_failure(ip)
    return render_template("login.html", error="Incorrect password."), 401


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ---------------------------------------------------------------------------
# Dashboard / cluster / vms / storage / backups / network / logs / settings
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    devices, statuses = get_device_statuses()
    proxmox = get_cluster_health()
    net = check_network_health()
    return render_template("dashboard.html", devices=devices, statuses=statuses, logs=get_logs(), proxmox=proxmox, net=net, page="dashboard")


@app.route("/cluster")
def cluster():
    devices, statuses = get_device_statuses()
    proxmox = get_cluster_health()
    return render_template("cluster.html", devices=devices, statuses=statuses, proxmox=proxmox, page="cluster")


@app.route("/vms")
def vms():
    proxmox = get_cluster_health()
    return render_template("vms.html", proxmox=proxmox, page="vms")


@app.route("/storage")
def storage():
    proxmox = get_cluster_health()
    return render_template("storage.html", proxmox=proxmox, page="storage")


@app.route("/backups")
def backups():
    proxmox = get_cluster_health()
    backup = get_backup_info()
    return render_template("backups.html", proxmox=proxmox, backup=backup, page="backups")


@app.route("/network")
def network():
    devices, statuses = get_device_statuses()
    return render_template("network.html", devices=devices, statuses=statuses, page="network")


@app.route("/logs")
def logs():
    return render_template("logs.html", logs=get_logs(), page="logs")


@app.route("/settings")
def settings():
    devices, statuses = get_device_statuses()
    return render_template("settings.html", devices=devices, statuses=statuses, page="settings")


@app.route("/wireguard")
def wireguard_page():
    return render_template("wireguard.html", page="wireguard")


@app.route("/api/wireguard/peers")
def api_wireguard_peers():
    try:
        return jsonify({"ok": True, "peers": wg_list_peers()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/wireguard/peers", methods=["POST"])
def api_wireguard_create_peer():
    import io, base64
    import qrcode

    payload = request.get_json(silent=True) or {}
    try:
        peer = wg_generate_peer(payload.get("name"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    img = qrcode.make(peer["config_text"])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    log_event("network", "wireguard", f'New WireGuard peer "{peer["name"]}" generated ({peer["address"]})',
              metadata={"name": peer["name"], "address": peer["address"]})

    return jsonify({"ok": True, "peer": peer, "qr_code_base64": qr_b64})


@app.route("/app-config")
def app_config_page():
    return render_template("app_config.html", config=get_all_config(), page="settings")


@app.route("/security")
def security():
    wazuh = get_wazuh_summary()
    return render_template("security.html", wazuh=wazuh, page="security")


@app.route("/security/agent/<agent_id>")
def security_agent(agent_id):
    details = get_agent_security(agent_id)
    return render_template("security_agent.html", details=details, page="security")


@app.route("/hue-scenes")
def hue_scenes_page():
    return render_template("hue_scenes.html", page="hue-scenes", hue=hue_bridge_status(), scenes=load_scene_registry())


@app.route("/music")
def music_page():
    return render_template("music.html", page="music")


@app.route("/automations")
def automations_page():
    return render_template("automations.html", page="automations")


@app.route("/mission-control")
def mission_control_page():
    return render_template("wallboard.html")


@app.route("/api/mission-control")
def api_mission_control():
    maybe_snapshot_wazuh()

    proxmox = get_cluster_health()
    wazuh = get_wazuh_summary()
    net = check_network_health()
    devices, statuses = get_device_statuses()
    active_scenario = get_active_scenario()

    trend_events = get_events_by_type("wazuh_snapshot", limit=20)
    vuln_trend = [e["metadata"]["vulnerabilities"].get("total", 0) for e in trend_events if e.get("metadata", {}).get("vulnerabilities")]
    agent_trend = [e["metadata"]["health"].get("active_agents", 0) for e in trend_events if e.get("metadata", {}).get("health")]

    return jsonify({
        "ok": True,
        "proxmox": proxmox,
        "wazuh": wazuh,
        "network": net,
        "statuses": statuses,
        "devices": devices,
        "assessment": build_assessment(proxmox, wazuh),
        "incident_mode": bool(active_scenario),
        "active_scenario": active_scenario,
        "vuln_trend": vuln_trend,
        "agent_trend": agent_trend,
        "logs": get_logs(),
    })


# ---------------------------------------------------------------------------
# Music (browser playback only - no Pi/SSH involved, safe to run alongside
# whatever the Pi endpoint is doing elsewhere)
# ---------------------------------------------------------------------------

MUSIC_ALLOWED_EXT = {".mp3", ".ogg", ".wav", ".m4a"}


@app.route("/api/music/tracks")
def api_music_tracks():
    return jsonify({"ok": True, "tracks": list_tracks()})


@app.route("/api/music/artwork/<path:file_name>")
def api_music_artwork(file_name):
    from modules.music_output import get_artwork_path
    cache_path, mime = get_artwork_path(file_name)
    if not cache_path:
        return "", 404
    response = send_file(cache_path, mimetype=mime)
    response.headers["Cache-Control"] = "private, max-age=86400"
    return response


@app.route("/api/music/upload", methods=["POST"])
def api_music_upload():
    music_dir = Path("static/music")
    music_dir.mkdir(parents=True, exist_ok=True)
    files = request.files.getlist("files")
    saved, rejected = [], []
    for f in files:
        filename = secure_filename(f.filename or "")
        if not filename:
            continue
        ext = Path(filename).suffix.lower()
        if ext not in MUSIC_ALLOWED_EXT:
            rejected.append({"file": filename, "reason": "Unsupported file type. Use MP3, OGG, WAV, or M4A."})
            continue
        target = music_dir / filename
        counter = 1
        while target.exists():
            target = music_dir / f"{Path(filename).stem}_{counter}{ext}"
            counter += 1
        f.save(target)
        saved.append({"file": target.name})
    return jsonify({"ok": True, "saved": saved, "rejected": rejected, "tracks": list_tracks()})


@app.route("/api/music/delete", methods=["POST"])
def api_music_delete():
    payload = request.get_json(silent=True) or {}
    return jsonify(delete_track(payload.get("file")))


@app.route("/api/music/control", methods=["POST"])
def api_music_control():
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "").strip().lower()

    if action == "stop":
        log_event("music", "music", "Music stopped manually")
        return jsonify({"ok": True, **set_music_command("stop")})
    if action == "play":
        file = payload.get("file")
        if not file:
            return jsonify({"ok": False, "error": "Missing file"}), 400
        log_event("music", "music", f"Playing \"{file}\" manually", metadata={"file": file})
        return jsonify({"ok": True, **set_music_command(
            "play", file=file,
            loop=bool(payload.get("loop", False)),
            after_track=payload.get("after_track", "stop"),
        )})
    if action == "shuffle":
        log_event("music", "music", "Shuffle play started manually")
        return jsonify(shuffle_command())

    return jsonify({"ok": False, "error": "Unsupported action"}), 400


@app.route("/api/music/command")
def api_music_command_route():
    return jsonify(get_music_command())


@app.route("/api/music/advance", methods=["POST"])
def api_music_advance():
    """Called by the browser when a track finishes, to find out what plays
    next based on the after_track behavior of the command that just ended."""
    payload = request.get_json(silent=True) or {}
    mode = str(payload.get("after_track") or "stop").strip()
    current_file = payload.get("file")

    if mode == "shuffle":
        return jsonify(shuffle_command())
    if mode == "playlist":
        nxt = next_track_after(current_file)
        if not nxt:
            return jsonify({"ok": False, "error": "No tracks available"})
        return jsonify({"ok": True, **set_music_command("play", file=nxt["file"], after_track="playlist")})
    if mode == "queue":
        nxt = next_track_after(current_file)
        if not nxt:
            return jsonify({"ok": True, **set_music_command("stop")})
        current_cmd = get_music_command()
        return jsonify({"ok": True, **set_music_command("play", file=nxt["file"], after_track="queue", queue=current_cmd.get("queue"))})

    return jsonify({"ok": True, **set_music_command("stop")})


# ---------------------------------------------------------------------------
# Playlists
# ---------------------------------------------------------------------------

@app.route("/api/playlists")
def api_playlists_list():
    return jsonify({"ok": True, "playlists": list_playlists()})


@app.route("/api/playlists/manage", methods=["POST"])
def api_playlists_create():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, "playlist": create_playlist(payload.get("name"))})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/playlists/manage/<playlist_id>", methods=["PUT", "POST"])
def api_playlists_update(playlist_id):
    payload = request.get_json(silent=True) or {}
    try:
        if "name" in payload:
            rename_playlist(playlist_id, payload["name"])
        if "tracks" in payload:
            set_playlist_tracks(playlist_id, payload["tracks"])
        playlist = get_playlist(playlist_id)
        if not playlist:
            return jsonify({"ok": False, "error": "Playlist not found"}), 404
        return jsonify({"ok": True, "playlist": playlist})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/playlists/manage/<playlist_id>", methods=["DELETE"])
def api_playlists_delete(playlist_id):
    return jsonify(delete_playlist(playlist_id))


@app.route("/api/playlists/manage/<playlist_id>/play", methods=["POST"])
def api_playlists_play(playlist_id):
    log_event("music", "music", f"Playlist \"{playlist_id}\" started manually", metadata={"playlist_id": playlist_id})
    return jsonify(play_playlist(playlist_id))


# ---------------------------------------------------------------------------
# Automations
# ---------------------------------------------------------------------------

@app.route("/api/automations")
def api_automations():
    return jsonify({"ok": True, "automations": list_automations()})


@app.route("/api/automations/manage", methods=["POST"])
def api_automations_create():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, "automation": create_or_update_automation(payload)})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/automations/manage/<automation_id>", methods=["PUT", "POST"])
def api_automations_update(automation_id):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, "automation": create_or_update_automation(payload, existing_id=automation_id)})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/automations/manage/<automation_id>", methods=["DELETE"])
def api_automations_delete(automation_id):
    return jsonify(delete_automation(automation_id))


@app.route("/api/automations/manage/<automation_id>/enabled", methods=["POST"])
def api_automations_toggle(automation_id):
    payload = request.get_json(silent=True) or {}
    record = set_automation_enabled(automation_id, payload.get("enabled", True))
    if not record:
        return jsonify({"ok": False, "error": "Automation not found"}), 404
    return jsonify({"ok": True, "automation": record})


@app.route("/api/automations/run", methods=["POST"])
def api_automations_run():
    payload = request.get_json(silent=True) or {}
    automation_id = payload.get("id")
    if not automation_id:
        return jsonify({"ok": False, "error": "Missing automation id"}), 400
    return jsonify(run_automation(automation_id))


# ---------------------------------------------------------------------------
# Device power
# ---------------------------------------------------------------------------

@app.route("/wake/<key>")
def wake(key):
    wake_device(key)
    return redirect("/")


@app.route("/start")
def start():
    start_cerberus_net()
    return redirect("/")


@app.route("/api/device/power", methods=["POST"])
def api_device_power():
    payload = request.get_json(silent=True) or {}
    raw_name = str(payload.get("name") or payload.get("device") or payload.get("target") or "").strip().lower()
    action_name = str(payload.get("action", "")).strip().lower()
    key = raw_name.replace(" ", "_").replace("-", "_")

    devices = load_devices()
    dev = devices.get(key)
    if not dev:
        return jsonify({"ok": False, "error": f"Unknown device: {raw_name}"}), 404
    if dev.get("enabled", True) is False:
        return jsonify({"ok": False, "error": f"{dev['name']} is disabled/not configured."}), 409

    if action_name in {"wake", "start", "on", "poweron", "power_on"}:
        wake_device(key)
        log_event("power", "device_power", f"Wake sent to \"{dev['name']}\"", metadata={"device": key, "action": "wake"})
        return jsonify({"ok": True, "message": f"{dev['name']}: wake sent"})

    if action_name in {"shutdown", "shut_down", "poweroff", "power_off", "off"}:
        if dev.get("shutdown_method") != "proxmox":
            return jsonify({"ok": False, "error": f"{dev['name']} is not configured for Proxmox shutdown."}), 409
        node = dev.get("node") or key
        try:
            result = node_shutdown(node)
            log(f"{dev['name']}: Proxmox shutdown requested")
            log_event("power", "device_power", f"Shutdown requested for \"{dev['name']}\"", severity="warning", metadata={"device": key, "action": "shutdown"})
            return jsonify({"ok": True, "message": f"{dev['name']}: shutdown requested", "result": result})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": False, "error": "Missing name or unsupported action", "received": payload}), 400


# ---------------------------------------------------------------------------
# Status / summary APIs
# ---------------------------------------------------------------------------

@app.route("/api/status")
def api_status():
    devices, statuses = get_device_statuses()
    return jsonify({"statuses": statuses, "logs": get_logs()})


@app.route("/api/health")
def api_health():
    return jsonify(get_cluster_health())


@app.route("/api/backups")
def api_backups():
    return jsonify(get_backup_info())


@app.route("/api/network")
def api_network():
    return jsonify(check_network_health())


@app.route("/api/proxmox/endpoints")
def api_proxmox_endpoints():
    return jsonify(get_proxmox_endpoints())


@app.route("/api/proxmox/active")
def api_proxmox_active():
    return jsonify(get_active_proxmox_endpoint())


@app.route("/api/wazuh")
def api_wazuh():
    return jsonify(get_wazuh_summary())


@app.route("/api/security/agent/<agent_id>")
def api_security_agent(agent_id):
    return jsonify(get_agent_security(agent_id))


@app.route("/api/summary")
def api_summary():
    devices, statuses = get_device_statuses()
    return jsonify({
        "statuses": statuses,
        "proxmox": get_cluster_health(),
        "backup": get_backup_info(),
        "network": check_network_health(),
        "wazuh": get_wazuh_summary(),
        "logs": get_logs(),
    })


@app.route("/api/hades/guests")
def api_hades_guests():
    # Deliberately status-only - no action routes exist for Hades guests.
    # These live on an air-gapped detonation network and should only ever
    # be reverted from a clean snapshot, not driven through the normal
    # start/stop/migrate VM actions.
    return jsonify(get_hades_guests())


@app.route("/operations-queue")
def operations_queue_page():
    return render_template("operations_queue.html", page="operations-queue")


@app.route("/api/operations/queue")
def api_operations_queue():
    return jsonify({"ok": True, "items": list_operations()})


# ---------------------------------------------------------------------------
# VM actions
# ---------------------------------------------------------------------------

def _resolve_vm_payload(payload):
    payload = dict(payload or {})
    vmid = str(payload.get("vmid") or "").strip()
    node = str(payload.get("node") or "").strip()
    name = str(payload.get("name") or "").strip()

    try:
        proxmox = get_cluster_health()
        for vm in proxmox.get("vms", []):
            vm_name = vm.get("name") or f"VM {vm.get('vmid')}"
            matches_vmid = vmid and str(vm.get("vmid")) == vmid
            matches_name = name and str(vm_name).lower() == name.lower()
            if matches_vmid or matches_name:
                payload["vmid"] = vmid or vm.get("vmid")
                payload["node"] = node or vm.get("node")
                payload["name"] = name or vm_name
                break
    except Exception:
        pass

    return payload


def _json_error(message, code=500, job=None):
    payload = {"ok": False, "error": str(message)}
    if job:
        payload["job"] = job
    return jsonify(payload), code


def _payload():
    data = {}
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}
    if not data and request.form:
        data = dict(request.form)
    if not data and request.args:
        data = dict(request.args)
    return data


@app.route("/api/vm/action", methods=["POST"])
def api_vm_action():
    payload = _resolve_vm_payload(_payload())
    node, vmid, action_name = payload.get("node"), payload.get("vmid"), payload.get("action")
    name = payload.get("name") or f"VM {vmid}"

    if not node or not vmid or not action_name:
        return _json_error("Missing node, vmid, or action.", 400)

    job = add_operation(f"vm_{action_name}", name, status="running", detail=f"Requested {action_name} for {name}", metadata=payload)
    try:
        result = vm_action(node, vmid, action_name)
        updated = update_operation(job["id"], "submitted", f"Proxmox task submitted: {result}", {"upid": result, "node": node})
        log_event("proxmox", "vm_action", f"VM \"{name}\" {action_name} submitted", metadata={"node": node, "vmid": vmid, "action": action_name})
        return jsonify({"ok": True, "job": updated})
    except Exception as e:
        updated = update_operation(job["id"], "failed", str(e))
        return _json_error(str(e), 500, updated or job)


@app.route("/api/vm/backup", methods=["POST"])
def api_vm_backup():
    payload = _resolve_vm_payload(_payload())
    node, vmid = payload.get("node"), payload.get("vmid")
    name = payload.get("name") or f"VM {vmid}"

    if not node or not vmid:
        return _json_error("Missing node or vmid.", 400)

    job = add_operation("vm_backup", name, status="running", detail=f"Requested backup for {name}", metadata=payload)
    try:
        result = vm_backup(node, vmid, storage=payload.get("storage"))
        updated = update_operation(job["id"], "submitted", f"Backup task submitted: {result}", {"upid": result, "node": node})
        log_event("proxmox", "vm_backup", f"Backup submitted for VM \"{name}\"", metadata={"node": node, "vmid": vmid})
        return jsonify({"ok": True, "job": updated})
    except Exception as e:
        updated = update_operation(job["id"], "failed", str(e))
        return _json_error(str(e), 500, updated or job)


@app.route("/api/vm/snapshot", methods=["POST"])
def api_vm_snapshot():
    payload = _resolve_vm_payload(_payload())
    node, vmid = payload.get("node"), payload.get("vmid")
    name = payload.get("name") or f"VM {vmid}"

    if not node or not vmid:
        return _json_error("Missing node or vmid.", 400)

    job = add_operation("vm_snapshot", name, status="running", detail=f"Requested snapshot for {name}", metadata=payload)
    try:
        result = vm_snapshot(node, vmid, snapname=payload.get("snapname"))
        updated = update_operation(job["id"], "submitted", f"Snapshot task submitted: {result}", {"upid": result, "node": node})
        log_event("proxmox", "vm_snapshot", f"Snapshot submitted for VM \"{name}\"", metadata={"node": node, "vmid": vmid})
        return jsonify({"ok": True, "job": updated})
    except Exception as e:
        updated = update_operation(job["id"], "failed", str(e))
        return _json_error(str(e), 500, updated or job)


@app.route("/api/vm/monitor", methods=["POST"])
def api_vm_monitor():
    payload = _resolve_vm_payload(_payload())
    node, vmid = payload.get("node"), payload.get("vmid")
    command = payload.get("command") or "info status"
    name = payload.get("name") or f"VM {vmid}"

    if not node or not vmid:
        return _json_error("Missing node or vmid.", 400)

    job = add_operation("vm_monitor", name, status="running", detail=f"Requested monitor command '{command}' for {name}", metadata=payload)
    try:
        result = vm_monitor_command(node, vmid, command)
        updated = update_operation(job["id"], "submitted", f"Monitor command returned: {result}", {"result": result, "node": node})
        return jsonify({"ok": True, "job": updated, "result": result})
    except Exception as e:
        updated = update_operation(job["id"], "failed", str(e))
        return _json_error(str(e), 500, updated or job)


@app.route("/api/vm/migrate", methods=["POST"])
def api_vm_migrate():
    payload = _resolve_vm_payload(_payload())
    node, vmid, target = payload.get("node"), payload.get("vmid"), payload.get("target")
    name = payload.get("name") or f"VM {vmid}"

    if not node or not vmid or not target:
        return _json_error("Missing node, vmid, or target.", 400)

    job = add_operation("vm_migrate", name, status="running", detail=f"Requested migration for {name} from {node} to {target}", metadata=payload)
    try:
        result = vm_migrate(node, vmid, target, online=bool(payload.get("online", True)))
        updated = update_operation(job["id"], "submitted", f"Migration task submitted: {result}", {"upid": result, "node": node, "target": target})
        return jsonify({"ok": True, "job": updated})
    except Exception as e:
        updated = update_operation(job["id"], "failed", str(e))
        return _json_error(str(e), 500, updated or job)


@app.route("/api/vm/clone", methods=["POST"])
def api_vm_clone():
    payload = _resolve_vm_payload(_payload())
    node, vmid, newid = payload.get("node"), payload.get("vmid"), payload.get("newid")
    name = payload.get("clone_name") or payload.get("newname")
    source_name = payload.get("name") or f"VM {vmid}"

    if not node or not vmid or not newid:
        return _json_error("Missing node, vmid, or newid.", 400)

    job = add_operation("vm_clone", source_name, status="running", detail=f"Requested clone of {source_name} to VMID {newid}", metadata=payload)
    try:
        result = vm_clone(node, vmid, newid, name=name, full=bool(payload.get("full", True)), target=payload.get("target"))
        updated = update_operation(job["id"], "submitted", f"Clone task submitted: {result}", {"upid": result, "node": node, "newid": newid})
        return jsonify({"ok": True, "job": updated})
    except Exception as e:
        updated = update_operation(job["id"], "failed", str(e))
        return _json_error(str(e), 500, updated or job)


@app.route("/api/vm/console", methods=["POST"])
def api_vm_console():
    payload = _resolve_vm_payload(_payload())
    node, vmid = payload.get("node"), payload.get("vmid")
    name = payload.get("name") or f"VM {vmid}"

    if not node or not vmid:
        return _json_error("Missing node or vmid.", 400)

    job = add_operation("vm_console", name, status="submitted", detail=f"Console requested for {name}", metadata=payload)
    try:
        ui_url = proxmox_vm_ui_url(node, vmid)
        try:
            proxy = vm_console_proxy(node, vmid)
        except Exception as inner:
            proxy = {"error": str(inner)}
        return jsonify({"ok": True, "job": job, "url": ui_url, "proxy": proxy})
    except Exception as e:
        updated = update_operation(job["id"], "failed", str(e))
        return _json_error(str(e), 500, updated or job)


@app.route("/api/vm/backup-all", methods=["POST"])
def api_vm_backup_all():
    payload = _payload()
    proxmox = get_cluster_health()
    jobs = []
    for vm in proxmox.get("vms", []):
        node, vmid = vm.get("node"), vm.get("vmid")
        name = vm.get("name") or f"VM {vmid}"
        job = add_operation("vm_backup", name, status="running", detail=f"Requested backup for {name}", metadata={"node": node, "vmid": vmid})
        try:
            result = vm_backup(node, vmid, storage=payload.get("storage"))
            jobs.append(update_operation(job["id"], "submitted", f"Backup task submitted: {result}", {"upid": result, "node": node}))
        except Exception as e:
            jobs.append(update_operation(job["id"], "failed", str(e)))
    return jsonify({"ok": True, "jobs": jobs})


# ---------------------------------------------------------------------------
# Hue
# ---------------------------------------------------------------------------

@app.route("/api/hue/status")
def api_hue_status():
    return jsonify(hue_bridge_status())


@app.route("/api/hue/scenes", methods=["GET", "POST"])
def api_hue_scenes():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        return jsonify({"ok": True, "scenes": save_scene_registry(data.get("scenes", []))})
    return jsonify({"ok": True, "scenes": load_scene_registry()})


@app.route("/api/hue/scene/<name>/trigger", methods=["POST"])
def api_hue_scene_trigger(name):
    result = set_scene(name)
    log_event("hue", "hue_scene", f"Hue scene \"{name}\" triggered manually", metadata={"scene": name})
    return jsonify(result)


@app.route("/api/hue/lights", methods=["POST"])
def api_hue_lights():
    payload = request.get_json(silent=True) or {}
    return jsonify(set_lights(
        color=payload.get("color", "blue"),
        bri=payload.get("bri", 180),
        transitiontime=payload.get("transitiontime", 8),
        effect=payload.get("effect"),
    ))


# ---------------------------------------------------------------------------
# App configuration editor
# ---------------------------------------------------------------------------

@app.route("/api/config/all")
def api_config_all():
    return jsonify({"ok": True, "config": get_all_config()})


@app.route("/api/config/<name>", methods=["GET", "POST"])
def api_config_name(name):
    if name not in {"hue", "proxmox", "wazuh", "devices"}:
        return jsonify({"ok": False, "error": f"Unknown config: {name}"}), 404
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        return jsonify({"ok": True, "config": save_yaml_config(name, data)})
    return jsonify({"ok": True, "config": get_yaml_config(name)})


# ---------------------------------------------------------------------------
# Voice (Pi endpoint). The Pi's own wake-word loop posts audio to the first
# two routes; a token in PI_TOKEN_PATHS gates them instead of a session,
# since a headless script can't log in. Everything else here is behind the
# normal session auth like the rest of the app.
# ---------------------------------------------------------------------------

def _save_uploaded_audio():
    audio = request.files.get("audio")
    if not audio:
        return None
    fd, path = tempfile.mkstemp(suffix=".wav", dir="/tmp")
    import os
    with os.fdopen(fd, "wb") as f:
        audio.save(f)
    return path


@app.route("/api/voice/transcribe-audio", methods=["POST"])
def api_voice_transcribe_audio():
    import os
    path = _save_uploaded_audio()
    if not path:
        return jsonify({"ok": False, "error": "Missing audio file"}), 400
    try:
        return jsonify(transcribe_audio_file(path))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@app.route("/api/voice/command-audio", methods=["POST"])
def api_voice_command_audio():
    import os
    path = _save_uploaded_audio()
    if not path:
        return jsonify({"ok": False, "error": "Missing audio file"}), 400
    try:
        return jsonify(process_voice_command_file(path))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@app.route("/api/voice/command-audio-browser", methods=["POST"])
def api_voice_command_audio_browser():
    # Session-authenticated (normal auth gate, not the Pi token) - a human
    # in their own logged-in browser tab hit push-to-talk. Response audio
    # (if any) comes back inline as base64 so it plays through this same
    # browser tab's speakers by default, not the Pi's.
    import os
    path = _save_uploaded_audio()
    if not path:
        return jsonify({"ok": False, "error": "Missing audio file"}), 400
    try:
        result = process_voice_command_file(path, output="browser")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    audio_b64 = None
    for r in (result.get("automation") or {}).get("results", []):
        if r.get("type") == "speak" and r.get("ok"):
            wav_path = (r.get("result") or {}).get("wav_path")
            if wav_path and Path(wav_path).exists():
                audio_b64 = base64.b64encode(Path(wav_path).read_bytes()).decode("ascii")
                try:
                    os.remove(wav_path)
                except OSError:
                    pass
            break

    result["audio_base64"] = audio_b64
    return jsonify(result)


@app.route("/api/endpoints/heartbeat", methods=["POST"])
def api_endpoints_heartbeat():
    # No multi-endpoint registry in this build - one Pi, one Sentinel. This
    # just acknowledges so the Pi's heartbeat loop doesn't error every 30s.
    return jsonify({"ok": True})


@app.route("/api/voice/speak", methods=["POST"])
def api_voice_speak():
    payload = request.get_json(silent=True) or {}
    return jsonify(sentinel_say(payload.get("text", "")))


@app.route("/api/voice/listen", methods=["POST"])
def api_voice_listen():
    payload = request.get_json(silent=True) or {}
    return jsonify(record_pi_voice_command(payload.get("duration", 4)))


@app.route("/api/voice/listener/status")
def api_voice_listener_status():
    return jsonify(listener_status())


@app.route("/api/voice/listener/<action>", methods=["POST"])
def api_voice_listener_control(action):
    return jsonify(listener_control(action))


@app.route("/api/audio-settings", methods=["GET", "POST"])
def api_audio_settings():
    from modules.audio_settings import get_audio_settings, set_audio_settings
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        return jsonify({"ok": True, "settings": set_audio_settings(
            voice_volume=payload.get("voice_volume"),
            media_volume=payload.get("media_volume"),
        )})
    return jsonify({"ok": True, "settings": get_audio_settings()})


# ---------------------------------------------------------------------------
# Scenario Ops
# ---------------------------------------------------------------------------

@app.route("/scenario-ops")
def scenario_ops_page():
    devices, _ = get_device_statuses()
    return render_template("scenario_ops.html", page="scenario-ops", devices=devices)


@app.route("/api/scenarios")
def api_scenarios():
    return jsonify({"ok": True, "scenarios": list_scenarios(), "active": get_active_scenario()})


@app.route("/api/scenarios/start", methods=["POST"])
def api_scenarios_start():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, "scenario": start_scenario(payload)})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/scenarios/<scenario_id>/stop", methods=["POST"])
def api_scenarios_stop(scenario_id):
    scenario = stop_scenario(scenario_id)
    if not scenario:
        return jsonify({"ok": False, "error": "Scenario not found or already stopped"}), 404
    return jsonify({"ok": True, "scenario": scenario})


@app.route("/api/scenarios/<scenario_id>/note", methods=["POST"])
def api_scenarios_note(scenario_id):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, "scenario": add_note(scenario_id, payload.get("note"))})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/scenarios/<scenario_id>")
def api_scenario_get(scenario_id):
    scenario = get_scenario(scenario_id)
    if not scenario:
        return jsonify({"ok": False, "error": "Scenario not found"}), 404
    return jsonify({"ok": True, "scenario": scenario})


@app.route("/api/scenarios/<scenario_id>/report.md")
def api_scenario_report(scenario_id):
    report = render_report(scenario_id)
    if report is None:
        return jsonify({"ok": False, "error": "Scenario not found"}), 404
    filename = f"sentinel-scenario-{scenario_id}.md"
    return Response(report, mimetype="text/markdown", headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.route("/api/activity")
def api_activity():
    return jsonify({"ok": True, "events": get_recent_events(int(request.args.get("limit", 100)))})


if __name__ == "__main__":
    # threaded=True matters now: automation "wait" actions call time.sleep()
    # inside a request handler, and a single-threaded server would freeze
    # every other tab/user for the duration of that wait otherwise.

    # Second listener on 8443 with a self-signed cert, purely so the browser
    # treats this origin as a "secure context" - getUserMedia() (push-to-talk
    # mic capture) is unavailable on plain HTTP for any non-localhost host in
    # every modern browser, no way around that client-side. Port 8081 stays
    # exactly as it was for everything else (Pi calls, existing bookmarks).
    import os
    import threading
    from pathlib import Path as _Path

    # Localhost by default so a fresh clone is never LAN-reachable before
    # you've set a password and run scripts/verify_auth.py. Set
    # SENTINEL_BIND=0.0.0.0 once you've confirmed the auth gate holds.
    _bind = os.environ.get("SENTINEL_BIND", "127.0.0.1")
    _port = int(os.environ.get("SENTINEL_PORT", "8081"))
    _tls_port = int(os.environ.get("SENTINEL_TLS_PORT", "8443"))

    _cert = _Path("config/local/tls/cert.pem")
    _key = _Path("config/local/tls/key.pem")
    if _cert.exists() and _key.exists():
        from werkzeug.serving import run_simple
        threading.Thread(
            target=lambda: run_simple(
                _bind, _tls_port, app,
                ssl_context=(str(_cert), str(_key)),
                threaded=True,
            ),
            daemon=True,
        ).start()

    app.run(host=_bind, port=_port, threaded=True)
