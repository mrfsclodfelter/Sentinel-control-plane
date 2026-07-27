import requests
import urllib3
import time
import threading
from datetime import datetime, timezone
from collections import Counter
from modules.config import load_yaml

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_WAZUH_SUMMARY_CACHE = None
_WAZUH_SUMMARY_TS = 0.0
_WAZUH_SUMMARY_TTL = 30.0
_WAZUH_SUMMARY_REFRESHING = False
_WAZUH_SUMMARY_LOCK = threading.Lock()

def _cfg():
    return load_yaml("config/wazuh.yaml")

def _wazuh_cfg():
    return _cfg()["wazuh"]

def _indexer_cfg():
    return _cfg().get("indexer", {})

def _wazuh_base():
    c = _wazuh_cfg()
    return f"https://{c['host']}:{c.get('port', 55000)}"

def _indexer_base():
    c = _indexer_cfg()
    return f"https://{c['host']}:{c.get('port', 9200)}"

def _token():
    c = _wazuh_cfg()
    r = requests.get(
        _wazuh_base() + "/security/user/authenticate?raw=true",
        auth=(c["username"], c["password"]),
        verify=c.get("verify_ssl", False),
        timeout=8,
    )
    r.raise_for_status()
    return r.text.strip()

def _wazuh_get(path):
    token = _token()
    c = _wazuh_cfg()
    r = requests.get(
        _wazuh_base() + path,
        headers={"Authorization": f"Bearer {token}"},
        verify=c.get("verify_ssl", False),
        timeout=10,
    )
    r.raise_for_status()
    return r.json()

def _indexer_search(index, body):
    c = _indexer_cfg()
    if not c:
        raise RuntimeError("indexer config missing")
    r = requests.post(
        _indexer_base() + f"/{index}/_search",
        auth=(c["username"], c["password"]),
        verify=c.get("verify_ssl", False),
        timeout=12,
        headers={"Content-Type": "application/json"},
        json=body,
    )
    r.raise_for_status()
    return r.json()

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_wazuh_health():
    try:
        root = _wazuh_get("/")
        agents_summary = _wazuh_get("/agents/summary/status")
        agents = _wazuh_get("/agents?limit=1000")
        summary = agents_summary.get("data", {}).get("connection", {})
        agent_items = agents.get("data", {}).get("affected_items", [])
        active = int(summary.get("active", 0) or 0)
        disconnected = int(summary.get("disconnected", 0) or 0)
        never_connected = int(summary.get("never_connected", 0) or 0)
        pending = int(summary.get("pending", 0) or 0)
        total = active + disconnected + never_connected + pending
        return {
            "ok": True,
            "api": "online",
            "manager": root.get("data", {}).get("title", "Wazuh API"),
            "active_agents": active,
            "disconnected_agents": disconnected,
            "never_connected_agents": never_connected,
            "pending_agents": pending,
            "total_agents": total,
            "agents": agent_items,
            "checked_at": _now_iso(),
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False, "api": "offline", "manager": "Wazuh API",
            "active_agents": 0, "disconnected_agents": 0,
            "never_connected_agents": 0, "pending_agents": 0,
            "total_agents": 0, "agents": [], "checked_at": _now_iso(), "error": str(e)
        }

def _severity_bucket(sev):
    s = str(sev or "").lower()
    if s in ["critical", "high", "medium", "low"]:
        return s
    return "unknown"

def get_vulnerability_summary():
    empty = {
        "ok": False, "total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0,
        "recent": [], "top_agents": [], "top_packages": [], "error": None
    }
    try:
        body = {
            "size": 500,
            "_source": ["agent", "host.os", "package", "vulnerability"],
            "sort": [{"vulnerability.detected_at": {"order": "desc", "unmapped_type": "date"}}],
        }
        raw = _indexer_search("wazuh-states-vulnerabilities-*", body)
        hits = raw.get("hits", {}).get("hits", [])
        total = raw.get("hits", {}).get("total", {})
        total_value = total.get("value", len(hits)) if isinstance(total, dict) else len(hits)
        counts, agents, packages = Counter(), Counter(), Counter()
        recent = []
        for h in hits:
            src = h.get("_source", {})
            vuln = src.get("vulnerability", {})
            agent = src.get("agent", {})
            package = src.get("package", {})
            sev = _severity_bucket(vuln.get("severity"))
            counts[sev] += 1
            agents[agent.get("name", agent.get("id", "unknown"))] += 1
            packages[package.get("name", "unknown")] += 1
            if len(recent) < 12:
                score = vuln.get("score", {})
                recent.append({
                    "agent_id": agent.get("id", "-"),
                    "agent": agent.get("name", "-"),
                    "cve": vuln.get("id", "-"),
                    "severity": vuln.get("severity", "-"),
                    "score": score.get("base", "-") if isinstance(score, dict) else "-",
                    "package": package.get("name", "-"),
                    "description": vuln.get("description", "")[:240],
                    "detected_at": vuln.get("detected_at", "-"),
                })
        return {
            "ok": True,
            "total": total_value,
            "critical": counts["critical"],
            "high": counts["high"],
            "medium": counts["medium"],
            "low": counts["low"],
            "unknown": counts["unknown"],
            "recent": recent,
            "top_agents": [{"name": k, "count": v} for k, v in agents.most_common(6)],
            "top_packages": [{"name": k, "count": v} for k, v in packages.most_common(6)],
            "error": None,
        }
    except Exception as e:
        empty["error"] = str(e)
        return empty

def get_agent_security(agent_id):
    health = get_wazuh_health()
    agent = next((a for a in health.get("agents", []) if str(a.get("id")) == str(agent_id)), None)
    body = {
        "size": 250,
        "query": {"term": {"agent.id": str(agent_id)}},
        "_source": ["agent", "host.os", "package", "vulnerability"],
        "sort": [{"vulnerability.score.base": {"order": "desc", "unmapped_type": "float"}}],
    }
    try:
        raw = _indexer_search("wazuh-states-vulnerabilities-*", body)
        hits = raw.get("hits", {}).get("hits", [])
        counts, packages = Counter(), Counter()
        vulns = []
        for h in hits:
            src = h.get("_source", {})
            vuln = src.get("vulnerability", {})
            package = src.get("package", {})
            sev = _severity_bucket(vuln.get("severity"))
            counts[sev] += 1
            packages[package.get("name", "unknown")] += 1
            if len(vulns) < 50:
                score = vuln.get("score", {})
                vulns.append({
                    "cve": vuln.get("id", "-"),
                    "severity": vuln.get("severity", "-"),
                    "score": score.get("base", "-") if isinstance(score, dict) else "-",
                    "package": package.get("name", "-"),
                    "version": package.get("version", "-"),
                    "description": vuln.get("description", "")[:320],
                    "detected_at": vuln.get("detected_at", "-"),
                    "reference": vuln.get("reference", "-"),
                })
        return {
            "ok": True, "agent": agent,
            "counts": {"critical": counts["critical"], "high": counts["high"], "medium": counts["medium"], "low": counts["low"], "unknown": counts["unknown"], "total": len(hits)},
            "top_packages": [{"name": k, "count": v} for k, v in packages.most_common(10)],
            "vulnerabilities": vulns,
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "agent": agent, "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0, "total": 0}, "top_packages": [], "vulnerabilities": [], "error": str(e)}

def get_wazuh_alerts():
    try:
        body = {
            "size": 20,
            "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}],
            "_source": ["@timestamp", "agent", "rule"],
        }
        raw = _indexer_search("wazuh-alerts-*", body)
        hits = raw.get("hits", {}).get("hits", [])
        counts = Counter()
        alerts = []
        for h in hits:
            src = h.get("_source", {})
            rule = src.get("rule", {})
            level = int(rule.get("level", 0) or 0)
            if level >= 15: sev = "critical"
            elif level >= 12: sev = "high"
            elif level >= 7: sev = "medium"
            else: sev = "low"
            counts[sev] += 1
            alerts.append({"time": src.get("@timestamp", "-"), "agent": src.get("agent", {}).get("name", "-"), "rule": rule.get("description", "-"), "level": level, "severity": sev})
        return {"ok": True, "alerts": alerts, "critical": counts["critical"], "high": counts["high"], "medium": counts["medium"], "low": counts["low"], "total": len(alerts), "top_agent": "-", "top_rule": "-", "error": None}
    except Exception as e:
        return {"ok": False, "alerts": [], "critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0, "top_agent": "-", "top_rule": "-", "error": str(e)}


def get_threat_hunting_summary():
    empty = {"ok": False, "events": 0, "recent_alerts": [], "top_agents": [], "top_rules": [], "top_groups": [], "top_mitre": [], "severity_buckets": {"critical": 0, "high": 0, "medium": 0, "low": 0}, "error": None}
    try:
        body = {"size": 250, "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}], "_source": ["@timestamp", "agent", "rule", "decoder", "data", "full_log", "location"]}
        raw = _indexer_search("wazuh-alerts-*", body)
        hits = raw.get("hits", {}).get("hits", [])
        agents, rules, groups, mitre, buckets = Counter(), Counter(), Counter(), Counter(), Counter()
        recent = []
        for h in hits:
            src = h.get("_source", {})
            agent = src.get("agent", {}) or {}
            rule = src.get("rule", {}) or {}
            level = int(rule.get("level", 0) or 0)
            sev = "critical" if level >= 15 else "high" if level >= 12 else "medium" if level >= 7 else "low"
            buckets[sev] += 1
            agent_name = agent.get("name", "manager")
            rule_desc = rule.get("description", "Unknown rule")
            agents[agent_name] += 1
            rules[rule_desc] += 1
            for g in rule.get("groups", []) or []:
                groups[g] += 1
            mitre_data = rule.get("mitre", {}) or {}
            for t in mitre_data.get("tactic", []) or []:
                mitre[t] += 1
            if len(recent) < 12:
                recent.append({"time": src.get("@timestamp", "-"), "agent": agent_name, "rule": rule_desc, "level": level, "severity": sev, "groups": rule.get("groups", []) or [], "mitre": mitre_data, "location": src.get("location", "-")})
        return {"ok": True, "events": len(hits), "recent_alerts": recent, "top_agents": [{"name": k, "count": v} for k, v in agents.most_common(6)], "top_rules": [{"name": k, "count": v} for k, v in rules.most_common(6)], "top_groups": [{"name": k, "count": v} for k, v in groups.most_common(8)], "top_mitre": [{"name": k, "count": v} for k, v in mitre.most_common(6)], "severity_buckets": {"critical": buckets["critical"], "high": buckets["high"], "medium": buckets["medium"], "low": buckets["low"]}, "error": None}
    except Exception as e:
        empty["error"] = str(e)
        return empty

def _collect_wazuh_summary():
    health = get_wazuh_health()
    vulnerabilities = get_vulnerability_summary()
    alerts = get_wazuh_alerts()
    threat_hunting = get_threat_hunting_summary()
    if vulnerabilities.get("critical", 0) > 0 or alerts.get("critical", 0) > 0:
        threat = "CRITICAL"
    elif vulnerabilities.get("high", 0) > 0 or alerts.get("high", 0) > 0:
        threat = "HIGH"
    elif vulnerabilities.get("medium", 0) > 0 or alerts.get("medium", 0) > 0:
        threat = "ELEVATED"
    elif health.get("ok"):
        threat = "GREEN"
    else:
        threat = "UNKNOWN"
    return {"ok": health.get("ok") and vulnerabilities.get("ok", False), "health": health, "alerts": alerts, "threat_hunting": threat_hunting, "vulnerabilities": vulnerabilities, "threat_level": threat, "error": health.get("error") or vulnerabilities.get("error") or alerts.get("error")}



def _empty_wazuh_summary(refreshing=False):
    return {
        "ok": False,
        "cached": True,
        "refreshing": refreshing,
        "health": {"ok": False, "active_agents": 0, "total_agents": 0, "agents": [], "error": "Wazuh summary is refreshing"},
        "alerts": {"ok": False, "critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0, "alerts": [], "error": "Wazuh summary is refreshing"},
        "threat_hunting": {"ok": False, "events": 0, "recent_alerts": [], "top_agents": [], "top_rules": [], "error": "Wazuh summary is refreshing"},
        "vulnerabilities": {"ok": False, "total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0, "recent": [], "top_agents": [], "top_packages": [], "error": "Wazuh summary is refreshing"},
        "threat_level": "SYNCING",
        "error": "Wazuh summary is refreshing",
    }


def _refresh_wazuh_summary_cache():
    global _WAZUH_SUMMARY_CACHE, _WAZUH_SUMMARY_TS, _WAZUH_SUMMARY_REFRESHING
    try:
        data = _collect_wazuh_summary()
        data["cached"] = False
        with _WAZUH_SUMMARY_LOCK:
            _WAZUH_SUMMARY_CACHE = data
            _WAZUH_SUMMARY_TS = time.time()
    finally:
        with _WAZUH_SUMMARY_LOCK:
            _WAZUH_SUMMARY_REFRESHING = False


def _start_wazuh_summary_refresh():
    global _WAZUH_SUMMARY_REFRESHING
    with _WAZUH_SUMMARY_LOCK:
        if _WAZUH_SUMMARY_REFRESHING:
            return
        _WAZUH_SUMMARY_REFRESHING = True
    threading.Thread(target=_refresh_wazuh_summary_cache, daemon=True).start()


def get_wazuh_summary():
    global _WAZUH_SUMMARY_CACHE, _WAZUH_SUMMARY_TS
    now = time.time()
    with _WAZUH_SUMMARY_LOCK:
        cache = _WAZUH_SUMMARY_CACHE
        age = now - _WAZUH_SUMMARY_TS

    if cache is None:
        _start_wazuh_summary_refresh()
        return _empty_wazuh_summary(refreshing=True)

    if age > _WAZUH_SUMMARY_TTL:
        _start_wazuh_summary_refresh()

    out = dict(cache)
    out["cached"] = True
    out["cache_age_seconds"] = round(age, 2)
    return out
