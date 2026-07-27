import json
import time
import uuid
from pathlib import Path
from modules.atomic import atomic_write_json

LOG_PATH = Path("data/activity_log.json")
MAX_ENTRIES = 500


def _load():
    if not LOG_PATH.exists():
        return []
    try:
        return json.loads(LOG_PATH.read_text())
    except Exception:
        return []


def _save(items):
    atomic_write_json(LOG_PATH, items[-MAX_ENTRIES:])


def log_event(source, event_type, message, severity="info", metadata=None):
    """Record one activity event. Always goes to the rolling general log;
    also gets appended to whatever scenario is currently active, if any -
    that's how Scenario Ops captures "everything the app already tracks"
    without every subsystem needing to know about scenarios directly."""
    event = {
        "id": str(uuid.uuid4())[:8],
        "time": time.time(),
        "source": source,
        "type": event_type,
        "message": message,
        "severity": severity,
        "metadata": metadata or {},
    }
    items = _load()
    items.append(event)
    _save(items)

    try:
        from modules.scenario_ops import append_event_to_active_scenario
        append_event_to_active_scenario(event)
    except Exception:
        pass

    return event


def get_recent_events(limit=100):
    return list(reversed(_load()))[:limit]


def get_events_by_type(event_type, limit=50):
    matches = [e for e in _load() if e.get("type") == event_type]
    return matches[-limit:]


_LAST_WAZUH_SNAPSHOT = 0
WAZUH_SNAPSHOT_INTERVAL = 5 * 60  # throttle so wallboard page views don't spam the log


def maybe_snapshot_wazuh():
    """Opportunistic, throttled Wazuh snapshot for wallboard trend charts.
    No background scheduler - just piggybacks on whoever loads the
    wallboard, at most once every 5 minutes. Trend data builds up over
    actual usage instead of needing a dedicated poller."""
    global _LAST_WAZUH_SNAPSHOT
    now = time.time()
    if now - _LAST_WAZUH_SNAPSHOT < WAZUH_SNAPSHOT_INTERVAL:
        return
    _LAST_WAZUH_SNAPSHOT = now
    try:
        from modules.wazuh import get_wazuh_summary
        summary = get_wazuh_summary()
        vulns = summary.get("vulnerabilities", {})
        health = summary.get("health", {})
        log_event(
            "wazuh", "wazuh_snapshot",
            f"Wazuh snapshot: {health.get('active_agents', 0)}/{health.get('total_agents', 0)} agents, "
            f"vulns C:{vulns.get('critical', 0)} H:{vulns.get('high', 0)} M:{vulns.get('medium', 0)} L:{vulns.get('low', 0)}",
            metadata={"health": health, "vulnerabilities": vulns},
        )
    except Exception:
        pass
