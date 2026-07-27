"""Plain-English status summaries for the Mission Control wallboard - just
string templates over telemetry we already collect, not a model call."""


def infrastructure_assessment(proxmox):
    if not proxmox.get("ok"):
        return f"Proxmox API is unreachable: {proxmox.get('error') or 'unknown error'}."
    active = (proxmox.get("active_endpoint") or {}).get("active") or "unknown"
    if proxmox.get("quorum"):
        return f"Cluster quorum is healthy using {active} as the active API source. {proxmox.get('running_vms', 0)} VM(s) running."
    return f"Proxmox API is reachable via {active}, but cluster quorum is NOT healthy - check node connectivity."


def soc_assessment(wazuh):
    if not wazuh.get("ok"):
        return f"Wazuh telemetry is degraded: {wazuh.get('error') or 'unknown error'}."
    health = wazuh.get("health", {})
    vulns = wazuh.get("vulnerabilities", {})
    threat = wazuh.get("threat_level", "UNKNOWN")
    total_vulns = vulns.get("total", 0)
    return (
        f"Threat posture is {threat} with {total_vulns} indexed vulnerabilit{'y' if total_vulns == 1 else 'ies'} "
        f"({health.get('active_agents', 0)}/{health.get('total_agents', 0)} agents active)."
    )


def threat_hunting_assessment(wazuh):
    hunting = wazuh.get("threat_hunting", {})
    alerts = hunting.get("recent_alerts", [])
    if not alerts:
        return "0 recent alert records sampled from Wazuh alert indexes."
    top = alerts[0]
    return f"{len(alerts)} recent alert record(s) sampled. Most recent: L{top.get('level', '?')} {top.get('agent', '?')} — {top.get('rule', 'unspecified rule')}."


def recommended_action(wazuh):
    vulns = wazuh.get("vulnerabilities", {})
    critical = vulns.get("critical", 0)
    high = vulns.get("high", 0)
    if critical:
        return f"{critical} critical vulnerabilit{'y requires' if critical == 1 else 'ies require'} immediate review on affected agents."
    if high:
        return f"{high} high-severity vulnerabilit{'y is' if high == 1 else 'ies are'} outstanding - schedule remediation soon."
    return "No high-priority vulnerability action is currently required. Continue monitoring."


def build_assessment(proxmox, wazuh):
    return {
        "infrastructure": infrastructure_assessment(proxmox),
        "soc": soc_assessment(wazuh),
        "threat_hunting": threat_hunting_assessment(wazuh),
        "recommended_action": recommended_action(wazuh),
    }
