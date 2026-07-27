import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
from modules.atomic import atomic_write_text

QUEUE_PATH = Path("data/operations_queue.json")
QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load():
    if not QUEUE_PATH.exists():
        return []
    try:
        return json.loads(QUEUE_PATH.read_text())
    except Exception:
        return []


def _save(items):
    atomic_write_text(QUEUE_PATH, json.dumps(items[-250:], indent=2))


def add_operation(action, target, status="queued", detail="", metadata=None):
    items = _load()
    job = {
        "id": str(uuid.uuid4())[:8],
        "created_at": _now(),
        "updated_at": _now(),
        "action": action,
        "target": target,
        "status": status,
        "detail": detail,
        "metadata": metadata or {},
    }
    items.append(job)
    _save(items)
    return job


def update_operation(job_id, status, detail=None, metadata=None):
    items = _load()
    found = None
    for item in items:
        if item["id"] == job_id:
            item["status"] = status
            item["updated_at"] = _now()
            if detail is not None:
                item["detail"] = detail
            if metadata:
                item.setdefault("metadata", {}).update(metadata)
            found = item
            break
    _save(items)
    return found


def list_operations(limit=50):
    return list(reversed(_load()))[:limit]
