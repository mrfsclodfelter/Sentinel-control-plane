import requests, urllib3
import time
import threading
from modules.config import load_yaml

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_LAST_ACTIVE_ENDPOINT = None
_LAST_ENDPOINT_ERRORS = []
_CLUSTER_CACHE = None
_CLUSTER_CACHE_TS = 0.0
_CLUSTER_CACHE_TTL = 10.0
_CLUSTER_REFRESHING = False
_CLUSTER_LOCK = threading.Lock()
_BACKUP_CACHE = None
_BACKUP_CACHE_TS = 0.0
_BACKUP_CACHE_TTL = 30.0
_BACKUP_REFRESHING = False
_BACKUP_LOCK = threading.Lock()

def load_proxmox_config():
    return load_yaml("config/proxmox.yaml")

def _normalize_endpoint_config():
    raw = load_proxmox_config()
    verify_ssl = raw.get("verify_ssl", False)
    prox = raw.get("proxmox", {})

    if "host" in prox:
        host = str(prox.get("host"))
        port = prox.get("port", 8006)
        if ":" not in host:
            host = f"{host}:{port}"
        return {
            "primary": {
                "name": "primary",
                "host": host,
                "user": prox.get("user", "root@pam"),
                "token_name": prox.get("token_name") or str(prox.get("token_id", "root@pam!cerberus")).split("!")[-1],
                "token_value": prox.get("token_value") or prox.get("token_secret") or prox.get("secret"),
                "verify_ssl": prox.get("verify_ssl", verify_ssl),
            }
        }

    endpoints = {}
    for name, cfg in prox.items():
        if not isinstance(cfg, dict):
            continue
        host = str(cfg.get("host", ""))
        if not host:
            continue
        if ":" not in host:
            host = f"{host}:{cfg.get('port', 8006)}"
        endpoints[name] = {
            "name": name,
            "host": host,
            "user": cfg.get("user", "root@pam"),
            "token_name": cfg.get("token_name") or str(cfg.get("token_id", "root@pam!cerberus")).split("!")[-1],
            "token_value": cfg.get("token_value") or cfg.get("token_secret") or cfg.get("secret"),
            "verify_ssl": cfg.get("verify_ssl", verify_ssl),
        }
    return endpoints

def _auth_header(cfg):
    return {"Authorization": f"PVEAPIToken={cfg.get('user','root@pam')}!{cfg.get('token_name','cerberus')}={cfg.get('token_value')}"}

def _endpoint_get(cfg, path):
    base = f"https://{cfg['host']}/api2/json"
    r = requests.get(base + path, headers=_auth_header(cfg), verify=cfg.get("verify_ssl", False), timeout=2.0)
    r.raise_for_status()
    return r.json()["data"]

def _working_endpoint():
    global _LAST_ACTIVE_ENDPOINT, _LAST_ENDPOINT_ERRORS
    endpoints = _normalize_endpoint_config()
    if not endpoints:
        raise RuntimeError("No Proxmox endpoints configured")

    ordered = list(endpoints.values())
    if _LAST_ACTIVE_ENDPOINT and _LAST_ACTIVE_ENDPOINT in endpoints:
        preferred = endpoints[_LAST_ACTIVE_ENDPOINT]
        ordered = [preferred] + [e for e in ordered if e["name"] != _LAST_ACTIVE_ENDPOINT]

    errors = []
    for cfg in ordered:
        try:
            _endpoint_get(cfg, "/version")
            _LAST_ACTIVE_ENDPOINT = cfg["name"]
            _LAST_ENDPOINT_ERRORS = errors
            return cfg
        except Exception as e:
            errors.append({"name": cfg.get("name"), "host": cfg.get("host"), "error": str(e)})

    _LAST_ENDPOINT_ERRORS = errors
    details = " | ".join([f"{e['name']}@{e['host']}: {e['error']}" for e in errors])
    raise RuntimeError(f"No working Proxmox API endpoint. {details}")

def api_get(path):
    return _endpoint_get(_working_endpoint(), path)

def get_active_proxmox_endpoint():
    try:
        cfg = _working_endpoint()
        return {"ok": True, "active": cfg["name"], "host": cfg["host"], "errors": _LAST_ENDPOINT_ERRORS}
    except Exception as e:
        return {"ok": False, "active": None, "host": None, "errors": _LAST_ENDPOINT_ERRORS, "error": str(e)}

def get_proxmox_endpoints():
    endpoints = _normalize_endpoint_config()
    output = []
    for name, cfg in endpoints.items():
        item = {"name": name, "host": cfg["host"], "ok": False, "version": "-", "nodes": [], "vms": [], "storage": [], "cluster_status": [], "error": None}
        try:
            version = _endpoint_get(cfg, "/version")
            nodes = _endpoint_get(cfg, "/nodes")
            resources = _endpoint_get(cfg, "/cluster/resources")
            try:
                cluster_status = _endpoint_get(cfg, "/cluster/status")
            except Exception:
                cluster_status = []
            item["ok"] = True
            item["version"] = version.get("version", "-")
            item["nodes"] = nodes
            item["vms"] = [r for r in resources if r.get("type") == "qemu"]
            item["storage"] = [r for r in resources if r.get("type") == "storage"]
            item["cluster_status"] = cluster_status
        except Exception as e:
            item["error"] = str(e)
        output.append(item)
    primary = _choose_primary_cluster_endpoint(output)
    active = {"ok": bool(primary), "active": primary.get("name") if primary else None, "host": primary.get("host") if primary else None, "errors": [i for i in output if i.get("error")]}
    return {"ok": any(i["ok"] for i in output), "endpoints": output, "active": active}

def _choose_primary_cluster_endpoint(items):
    ok_items = [i for i in items if i.get("ok")]
    if not ok_items:
        return None

    # Cerberus Heavy/Light is the virtualization cluster. Osiris is the app host
    # and fallback API source, but it should not drive Mission quorum when the
    # Cerberus cluster is reachable.
    for item in ok_items:
        if item.get("name") == "cerberus" and len(item.get("nodes") or []) >= 1:
            return item

    # Fallback: use the endpoint that reports the most nodes, then most VMs.
    return sorted(
        ok_items,
        key=lambda i: (len(i.get("nodes") or []), len(i.get("vms") or [])),
        reverse=True,
    )[0]

def _collect_cluster_health():
    global _LAST_ACTIVE_ENDPOINT, _LAST_ENDPOINT_ERRORS
    endpoints = _normalize_endpoint_config()
    endpoint_items = []
    errors = []

    for name, cfg in endpoints.items():
        item = {"name": name, "host": cfg["host"], "ok": False, "version": "-", "nodes": [], "vms": [], "storage": [], "cluster_status": [], "error": None}
        try:
            version = _endpoint_get(cfg, "/version")
            nodes = _endpoint_get(cfg, "/nodes")
            resources = _endpoint_get(cfg, "/cluster/resources")
            cluster_status = _endpoint_get(cfg, "/cluster/status")
            item["ok"] = True
            item["version"] = version.get("version", "-")
            item["nodes"] = nodes
            item["vms"] = [r for r in resources if r.get("type") == "qemu"]
            item["storage"] = [r for r in resources if r.get("type") == "storage"]
            item["cluster_status"] = cluster_status
        except Exception as e:
            item["error"] = str(e)
            errors.append({"name": name, "host": cfg.get("host"), "error": str(e)})
        endpoint_items.append(item)

    primary = _choose_primary_cluster_endpoint(endpoint_items)
    if not primary:
        _LAST_ENDPOINT_ERRORS = errors
        return {"ok": False, "quorum": False, "qdevice": False, "qdevice_name": "Unknown", "qdevice_explicit": False, "qdevice_inferred": False, "osiris_online": False, "online_nodes": 0, "offline_nodes": 0, "nodes": [], "vms": [], "storage": [], "cluster_status": [], "membership": [], "running_vms": 0, "stopped_vms": 0, "endpoints": endpoint_items, "active_endpoint": {"ok": False, "active": None, "host": None, "errors": errors}, "error": "No working Proxmox API endpoint"}

    _LAST_ACTIVE_ENDPOINT = primary.get("name")
    _LAST_ENDPOINT_ERRORS = errors

    nodes = sorted(primary.get("nodes") or [], key=lambda x: x.get("node", ""))

    # Standalone PVE hosts (Osiris, Hades, and any future addition) are never
    # Cerberus cluster members - they never drive quorum/vms/storage, but
    # their own CPU/RAM/Disk telemetry still belongs on Mission Control's
    # node grid. Loop over every other reachable endpoint rather than
    # hardcoding each host by name, so adding another standalone node later
    # doesn't need another copy of this block.
    existing_names = {n.get("node") for n in nodes}
    for item in endpoint_items:
        if item.get("name") == primary.get("name") or not item.get("ok"):
            continue
        for n in (item.get("nodes") or []):
            if n.get("node") not in existing_names:
                nodes.append(n)
                existing_names.add(n.get("node"))
    nodes.sort(key=lambda x: x.get("node", ""))

    vms = sorted(primary.get("vms") or [], key=lambda x: int(x.get("vmid", 0)))
    storage = sorted(primary.get("storage") or [], key=lambda x: (x.get("node", ""), x.get("storage", "")))
    cluster_status = primary.get("cluster_status") or []
    cluster_item = next((i for i in cluster_status if i.get("type") == "cluster"), {})
    quorum = cluster_item.get("quorate") == 1

    explicit_qdevice = any(
        str(item.get("name", "")).lower() == "qdevice"
        or str(item.get("type", "")).lower() == "qdevice"
        or "qdevice" in str(item).lower()
        for item in cluster_status
    )

    running_vms = sum(1 for vm in vms if vm.get("status") == "running")
    online_nodes = sum(1 for n in nodes if n.get("status") == "online")
    offline_nodes = len(nodes) - online_nodes

    # This cluster runs on a real node-majority (no QDevice attached -
    # deliberately: Proxmox won't allow one on an odd node count without
    # --force, and multiple real nodes already have a natural majority).
    # Only report a QDevice when Proxmox's own cluster_status genuinely
    # says so - don't infer one from Osiris being reachable, which used to
    # produce a fictional "Osiris Witness" label long after Osiris stopped
    # playing that role.
    qdevice = explicit_qdevice
    quorum_model = "qdevice" if qdevice else f"{len(nodes)}-node majority"

    membership = []
    for item in cluster_status:
        entry = dict(item)
        if entry.get("type") == "cluster":
            entry["display_status"] = "quorate" if entry.get("quorate") == 1 else "not quorate"
            entry["display_votes"] = entry.get("nodes", "-")
        elif entry.get("type") == "node":
            entry["display_status"] = "online" if entry.get("online") == 1 else "offline"
            entry["display_votes"] = entry.get("votes", "1")
        else:
            entry["display_status"] = entry.get("online", "-")
            entry["display_votes"] = entry.get("votes", "-")
        membership.append(entry)

    return {
        "ok": True,
        "quorum": quorum,
        "qdevice": qdevice,
        "qdevice_name": "QDevice" if qdevice else None,
        "qdevice_explicit": explicit_qdevice,
        "quorum_model": quorum_model,
        "online_nodes": online_nodes,
        "offline_nodes": offline_nodes,
        "nodes": nodes,
        "vms": vms,
        "storage": storage,
        "cluster_status": cluster_status,
        "membership": membership,
        "running_vms": running_vms,
        "stopped_vms": len(vms) - running_vms,
        "endpoints": endpoint_items,
        "active_endpoint": {"ok": True, "active": primary.get("name"), "host": primary.get("host"), "errors": errors},
        "error": None,
        "cached": False,
    }

def _refresh_cluster_cache():
    global _CLUSTER_CACHE, _CLUSTER_CACHE_TS, _CLUSTER_REFRESHING
    try:
        data = _collect_cluster_health()
        with _CLUSTER_LOCK:
            _CLUSTER_CACHE = data
            _CLUSTER_CACHE_TS = time.time()
    finally:
        with _CLUSTER_LOCK:
            _CLUSTER_REFRESHING = False

def _start_cluster_refresh():
    global _CLUSTER_REFRESHING
    with _CLUSTER_LOCK:
        if _CLUSTER_REFRESHING:
            return
        _CLUSTER_REFRESHING = True
    t = threading.Thread(target=_refresh_cluster_cache, daemon=True)
    t.start()

def get_cluster_health():
    """Return Mission cluster state from Osiris-owned cache when possible.

    The UI should not block on Cerberus Heavy/Light API timeouts. If cached
    state exists, return it immediately and refresh in the background when it is
    stale. The Cerberus cluster is preferred as the top-level virtualization
    source; Osiris remains the application host and fallback endpoint.
    """
    global _CLUSTER_CACHE, _CLUSTER_CACHE_TS
    now = time.time()
    with _CLUSTER_LOCK:
        cache = _CLUSTER_CACHE
        age = now - _CLUSTER_CACHE_TS

    if cache is None:
        _refresh_cluster_cache()
        with _CLUSTER_LOCK:
            return _CLUSTER_CACHE

    if age > _CLUSTER_CACHE_TTL:
        _start_cluster_refresh()

    out = dict(cache)
    out["cached"] = True
    out["cache_age_seconds"] = round(age, 2)
    return out


def _endpoint_post(cfg, path, data=None):
    base = f"https://{cfg['host']}/api2/json"
    r = requests.post(base + path, headers=_auth_header(cfg), verify=cfg.get("verify_ssl", False), timeout=4.0, data=data or {})
    r.raise_for_status()
    return r.json().get("data")

def api_post(path, data=None):
    return _endpoint_post(_working_endpoint(), path, data)


def _endpoint_for_node(node_name):
    endpoints = _normalize_endpoint_config()
    errors = []
    for cfg in endpoints.values():
        try:
            nodes = _endpoint_get(cfg, "/nodes")
            if any(str(n.get("node")) == str(node_name) for n in nodes):
                return cfg
        except Exception as e:
            errors.append(f"{cfg.get('name')}@{cfg.get('host')}: {e}")
    raise RuntimeError(f"No Proxmox endpoint contains node {node_name}. " + " | ".join(errors))

def node_shutdown(node_name):
    cfg = _endpoint_for_node(node_name)
    return _endpoint_post(cfg, f"/nodes/{node_name}/status", {"command": "shutdown"})

def node_reboot(node_name):
    cfg = _endpoint_for_node(node_name)
    return _endpoint_post(cfg, f"/nodes/{node_name}/status", {"command": "reboot"})

def vm_action(node, vmid, action):
    allowed = {"start", "shutdown", "stop", "reboot", "reset"}
    if action not in allowed:
        raise ValueError(f"Unsupported VM action: {action}")
    return api_post(f"/nodes/{node}/qemu/{vmid}/status/{action}")

def vm_backup(node, vmid, storage=None, mode="snapshot", compress="zstd"):
    data = {"vmid": str(vmid), "mode": mode, "compress": compress}
    if storage:
        data["storage"] = storage
    return api_post(f"/nodes/{node}/vzdump", data)

def vm_snapshot(node, vmid, snapname=None, description="Created by Cerberus Ops"):
    import time
    if not snapname:
        snapname = f"cerberus-ops-{int(time.time())}"
    return api_post(f"/nodes/{node}/qemu/{vmid}/snapshot", {"snapname": snapname, "description": description})




def vm_monitor_command(node, vmid, command):
    # QEMU monitor commands are powerful. Only expose a small safe allowlist.
    allowed = {
        "info status",
        "info block",
        "info network",
        "info cpus",
        "info version",
        "info balloon",
    }
    if command not in allowed:
        raise ValueError(f"Unsupported monitor command: {command}")
    return api_post(f"/nodes/{node}/qemu/{vmid}/monitor", {"command": command})

def vm_migrate(node, vmid, target, online=True):
    data = {"target": target}
    if online:
        data["online"] = 1
    return api_post(f"/nodes/{node}/qemu/{vmid}/migrate", data)

def vm_clone(node, vmid, newid, name=None, full=True, target=None):
    data = {"newid": str(newid), "full": 1 if full else 0}
    if name:
        data["name"] = name
    if target:
        data["target"] = target
    return api_post(f"/nodes/{node}/qemu/{vmid}/clone", data)

def vm_console_proxy(node, vmid):
    return api_post(f"/nodes/{node}/qemu/{vmid}/vncproxy", {"websocket": 1})

def proxmox_vm_ui_url(node, vmid):
    cfg = _working_endpoint()
    # Directs user to the Proxmox web UI; browser may require Proxmox login.
    return f"https://{cfg['host']}/#v1:0:=qemu%2F{vmid}:4:::::::"

def get_task_status(node, upid):
    safe_upid = str(upid).replace("/", "%2F")
    return api_get(f"/nodes/{node}/tasks/{safe_upid}/status")

def get_hades_guests():
    """Read-only status for Hades's own guest VMs (remnux, flare-vm) -
    deliberately never merged into the main cluster VM list. These live on
    an air-gapped detonation network and should only ever be reverted from
    a clean snapshot, not driven through the normal start/stop/migrate VM
    actions, so this stays a separate, action-free read path by design."""
    endpoints = _normalize_endpoint_config()
    cfg = endpoints.get("hades")
    if not cfg:
        return {"ok": False, "guests": [], "error": "Hades endpoint not configured"}
    try:
        resources = _endpoint_get(cfg, "/cluster/resources")
        guests = sorted(
            [r for r in resources if r.get("type") == "qemu"],
            key=lambda x: int(x.get("vmid", 0)),
        )
        return {"ok": True, "guests": guests, "error": None}
    except Exception as e:
        return {"ok": False, "guests": [], "error": str(e)}

def _collect_backup_info():
    result = {"ok": True, "jobs": [], "recent_tasks": [], "error": None}
    try:
        result["jobs"] = sorted(api_get("/cluster/backup"), key=lambda x: str(x.get("starttime", "")))
    except Exception as e:
        result["ok"] = False
        result["error"] = f"Backup jobs unavailable: {e}"
    try:
        tasks = api_get("/cluster/tasks")
        vzdump_tasks = [t for t in tasks if "vzdump" in str(t).lower() or t.get("type") == "vzdump"]
        result["recent_tasks"] = sorted(vzdump_tasks, key=lambda t: int(t.get("starttime", 0) or 0), reverse=True)[:20]
    except Exception as e:
        result["error"] = (result["error"] + " | " if result["error"] else "") + f"Backup tasks unavailable: {e}"
    return result


def _empty_backup_info(refreshing=False):
    return {"ok": False, "jobs": [], "recent_tasks": [], "cached": True, "refreshing": refreshing, "error": "Backup telemetry is refreshing"}


def _refresh_backup_cache():
    global _BACKUP_CACHE, _BACKUP_CACHE_TS, _BACKUP_REFRESHING
    try:
        data = _collect_backup_info()
        data["cached"] = False
        with _BACKUP_LOCK:
            _BACKUP_CACHE = data
            _BACKUP_CACHE_TS = time.time()
    finally:
        with _BACKUP_LOCK:
            _BACKUP_REFRESHING = False


def _start_backup_refresh():
    global _BACKUP_REFRESHING
    with _BACKUP_LOCK:
        if _BACKUP_REFRESHING:
            return
        _BACKUP_REFRESHING = True
    threading.Thread(target=_refresh_backup_cache, daemon=True).start()


def get_backup_info():
    global _BACKUP_CACHE, _BACKUP_CACHE_TS
    now = time.time()
    with _BACKUP_LOCK:
        cache = _BACKUP_CACHE
        age = now - _BACKUP_CACHE_TS

    if cache is None:
        _start_backup_refresh()
        return _empty_backup_info(refreshing=True)

    if age > _BACKUP_CACHE_TTL:
        _start_backup_refresh()

    out = dict(cache)
    out["cached"] = True
    out["cache_age_seconds"] = round(age, 2)
    return out

