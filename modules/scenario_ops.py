import json
import time
import uuid
from pathlib import Path
from modules.atomic import atomic_write_json
from modules.devices import load_devices

STORE_PATH = Path("data/scenarios.json")

# Short, plain-English context for each event type, plus something to look
# up later - this is what turns a raw timeline into a readable report.
EVENT_EXPLANATIONS = {
    "vm_action": {
        "blurb": "A virtual machine power action (start/stop/reboot/reset) was submitted through Proxmox.",
        "reference": "Proxmox VE guest lifecycle actions - affects that VM's availability immediately.",
    },
    "vm_backup": {
        "blurb": "A VM backup job (vzdump) was submitted.",
        "reference": "Proxmox VE Backup and Restore (vzdump).",
    },
    "vm_snapshot": {
        "blurb": "A point-in-time VM snapshot was created.",
        "reference": "Proxmox VE Snapshots - a rollback point, not a substitute for a full backup.",
    },
    "device_power": {
        "blurb": "A wake or shutdown command was sent to a physical or cluster device.",
        "reference": "Wake-on-LAN (wake) / Proxmox node shutdown API (shutdown).",
    },
    "automation_run": {
        "blurb": "An automation chain executed - may have changed lighting, played music, or spoken a response.",
        "reference": "Sentinel Automations page has the full chain definition for this automation.",
    },
    "hue_scene": {
        "blurb": "A Philips Hue lighting scene was applied manually (not via an automation).",
        "reference": "Philips Hue Bridge REST API - PUT /lights/<id>/state.",
    },
    "music": {
        "blurb": "Browser music playback was started or stopped manually.",
        "reference": "Sentinel browser music player (mini-player / Music Library page).",
    },
    "wazuh_snapshot": {
        "blurb": "A snapshot of Wazuh agent health and vulnerability counts was captured for this scenario.",
        "reference": "Wazuh SIEM manager/indexer API - agent health and vulnerability index summary.",
    },
    "scenario": {
        "blurb": "A scenario lifecycle event (started, ended, or an analyst note).",
        "reference": "Sentinel Scenario Ops.",
    },
}


def _load():
    if not STORE_PATH.exists():
        return []
    try:
        return json.loads(STORE_PATH.read_text())
    except Exception:
        return []


def _save(items):
    atomic_write_json(STORE_PATH, items)


def _maybe_auto_stop():
    items = _load()
    changed = False
    now = time.time()
    for s in items:
        if s["status"] == "active" and s.get("time_limit_minutes"):
            deadline = s["started_at"] + s["time_limit_minutes"] * 60
            if now >= deadline:
                s["status"] = "complete"
                s["ended_at"] = now
                changed = True
    if changed:
        _save(items)


def list_scenarios():
    _maybe_auto_stop()
    return list(reversed(_load()))


def get_scenario(scenario_id):
    return next((s for s in _load() if s["id"] == scenario_id), None)


def get_active_scenario():
    _maybe_auto_stop()
    return next((s for s in _load() if s["status"] == "active"), None)


def start_scenario(payload):
    payload = payload or {}
    if get_active_scenario():
        raise ValueError("A scenario is already active - stop it before starting a new one")

    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Scenario name is required")

    time_limit = payload.get("time_limit_minutes")
    try:
        time_limit = float(time_limit) if time_limit else None
    except (TypeError, ValueError):
        time_limit = None

    items = _load()
    scenario = {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "scenario_type": str(payload.get("scenario_type") or "").strip(),
        "machines": [str(m) for m in (payload.get("machines") or [])],
        "status": "active",
        "started_at": time.time(),
        "ended_at": None,
        "time_limit_minutes": time_limit,
        "events": [],
        "manual_notes": [],
        "notes": str(payload.get("notes") or "").strip(),
    }
    items.append(scenario)
    _save(items)

    from modules.activity_log import log_event
    log_event("scenario", "scenario", f"Scenario \"{name}\" started", metadata={"scenario_id": scenario["id"]})
    _snapshot_wazuh(scenario["id"])
    return scenario


def stop_scenario(scenario_id):
    scenario = get_scenario(scenario_id)
    if not scenario or scenario["status"] != "active":
        return None

    # Log the end-of-scenario events *before* flipping status to complete -
    # append_event_to_active_scenario() only appends to scenarios still
    # marked active, so logging after the flip would silently drop them.
    _snapshot_wazuh(scenario_id)
    from modules.activity_log import log_event
    log_event("scenario", "scenario", f"Scenario \"{scenario['name']}\" ended", metadata={"scenario_id": scenario_id})

    items = _load()
    for s in items:
        if s["id"] == scenario_id and s["status"] == "active":
            s["status"] = "complete"
            s["ended_at"] = time.time()
    _save(items)
    return get_scenario(scenario_id)


def _snapshot_wazuh(scenario_id):
    try:
        from modules.wazuh import get_wazuh_summary
        summary = get_wazuh_summary()
        health = summary.get("health", {})
        vulns = summary.get("vulnerabilities", {})
        message = (
            f"Wazuh snapshot: {health.get('active_agents', 0)}/{health.get('total_agents', 0)} agents active, "
            f"threat level {summary.get('threat_level', 'UNKNOWN')}, "
            f"vulns C:{vulns.get('critical', 0)} H:{vulns.get('high', 0)} M:{vulns.get('medium', 0)} L:{vulns.get('low', 0)}"
        )
        from modules.activity_log import log_event
        log_event("wazuh", "wazuh_snapshot", message, metadata={"health": health, "vulnerabilities": vulns})
    except Exception:
        pass


def append_event_to_active_scenario(event):
    items = _load()
    changed = False
    for s in items:
        if s["status"] == "active":
            s["events"].append(event)
            changed = True
    if changed:
        _save(items)


def add_note(scenario_id, note):
    note = str(note or "").strip()
    if not note:
        raise ValueError("Note text is required")
    items = _load()
    found = None
    for s in items:
        if s["id"] == scenario_id:
            s.setdefault("manual_notes", []).append({"time": time.time(), "note": note})
            found = s
    _save(items)
    return found


def _fmt_time(ts):
    if not ts:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def render_report(scenario_id):
    scenario = get_scenario(scenario_id)
    if not scenario:
        return None

    try:
        devices = load_devices()
    except Exception:
        devices = {}

    machine_names = [devices.get(k, {}).get("name", k) for k in scenario.get("machines", [])]

    lines = [
        f"# Scenario Report: {scenario['name']}",
        "",
        f"**Type:** {scenario.get('scenario_type') or '-'}  ",
        f"**Machines involved:** {', '.join(machine_names) or '-'}  ",
        f"**Started:** {_fmt_time(scenario.get('started_at'))}  ",
        f"**Ended:** {_fmt_time(scenario.get('ended_at'))}  ",
    ]
    duration = (scenario.get("ended_at") or time.time()) - scenario["started_at"]
    lines.append(f"**Duration:** {round(duration / 60, 1)} minutes  ")
    lines.append(f"**Status:** {scenario.get('status')}  ")
    if scenario.get("notes"):
        lines += ["", f"**Scenario notes:** {scenario['notes']}"]

    lines += ["", "---", "", "## Activity Timeline", ""]

    events = scenario.get("events", [])
    if not events:
        lines.append("_No activity was captured during this scenario._")
    for event in events:
        explanation = EVENT_EXPLANATIONS.get(event.get("type"), {})
        lines.append(f"### {_fmt_time(event.get('time'))} — {event.get('message')}")
        lines.append(f"- **Source:** {event.get('source')}")
        lines.append(f"- **Type:** `{event.get('type')}`")
        if explanation.get("blurb"):
            lines.append(f"- **What this means:** {explanation['blurb']}")
        if explanation.get("reference"):
            lines.append(f"- **Reference:** {explanation['reference']}")
        lines.append("")

    if scenario.get("manual_notes"):
        lines += ["---", "", "## Analyst Notes", ""]
        for note in scenario["manual_notes"]:
            lines.append(f"- **{_fmt_time(note['time'])}:** {note['note']}")

    return "\n".join(lines)
