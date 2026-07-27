from __future__ import annotations

import subprocess
from typing import Any, Dict


PI_TARGET = "cerberus-noc"
SERVICE_NAME = "sentinel-listener"


def _run(command: list[str], timeout: int = 25) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
        }


def listener_status() -> Dict[str, Any]:
    active = _run(["ssh", PI_TARGET, f"systemctl is-active {SERVICE_NAME}"])
    enabled = _run(["ssh", PI_TARGET, f"systemctl is-enabled {SERVICE_NAME}"])

    active_text = active.get("stdout") or "unknown"
    enabled_text = enabled.get("stdout") or "unknown"

    return {
        "ok": active.get("ok") or active_text in ["active", "inactive", "failed"],
        "service": SERVICE_NAME,
        "pi_target": PI_TARGET,
        "active": active_text,
        "enabled": enabled_text,
        "is_active": active_text == "active",
        "is_enabled": enabled_text == "enabled",
        "status_result": active,
        "enabled_result": enabled,
    }


def listener_control(action: str) -> Dict[str, Any]:
    action = str(action or "status").strip().lower()

    if action == "status":
        return listener_status()

    allowed = ["start", "stop", "restart", "enable", "disable"]
    if action not in allowed:
        return {
            "ok": False,
            "error": f"Unsupported action: {action}",
            "allowed": allowed + ["status"],
        }

    result = _run(["ssh", PI_TARGET, f"sudo systemctl {action} {SERVICE_NAME}"], timeout=35)
    status = listener_status()

    return {
        "ok": result.get("ok"),
        "action": action,
        "service": SERVICE_NAME,
        "pi_target": PI_TARGET,
        "result": result,
        "status": status,
    }
