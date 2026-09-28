from datetime import datetime, timezone
import hashlib
import json
from typing import Any


EVENT_WEIGHTS = {"created": 40, "updated": 25, "removed": 15}


def _fingerprint(record: dict[str, Any]) -> str:
    metadata = record.get("metadata", {})
    comparable = {
        "name": record.get("name"), "category": record.get("category"),
        "subcategory": record.get("subcategory"), "business_type": record.get("business_type"),
        "established_year": record.get("established_year"), "location": record.get("location"),
        "address": record.get("address"), "contact": record.get("contact"),
        "osm_tags": metadata.get("osm_tags", {}), "osm_version": metadata.get("osm_version"),
        "osm_timestamp": metadata.get("osm_timestamp"),
    }
    return hashlib.sha256(json.dumps(comparable, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def detect_changes(previous: list[dict[str, Any]], current: list[dict[str, Any]], observed_ids: set[str], detected_at: str) -> list[dict[str, Any]]:
    old_by_id = {item.get("id"): item for item in previous}
    new_by_id = {item.get("id"): item for item in current}
    events: list[dict[str, Any]] = []
    for business_id, record in new_by_id.items():
        old = old_by_id.get(business_id)
        event_type = "created" if old is None else "updated" if _fingerprint(old) != _fingerprint(record) else None
        if event_type:
            events.append({
                "id": f"{business_id}:{event_type}:{detected_at}", "business_id": business_id,
                "type": event_type, "source": "openstreetmap", "detected_at": detected_at,
                "event_at": record.get("metadata", {}).get("osm_timestamp") or detected_at,
                "description": "OSM object created" if event_type == "created" else "OSM object changed",
                "details": {"name": record.get("name"), "osm_version": record.get("metadata", {}).get("osm_version")},
            })
    for business_id, record in old_by_id.items():
        if business_id not in observed_ids and business_id in new_by_id:
            events.append({
                "id": f"{business_id}:removed:{detected_at}", "business_id": business_id,
                "type": "removed", "source": "openstreetmap", "detected_at": detected_at,
                "event_at": detected_at, "description": "OSM object was not returned by the latest crawl",
                "details": {"name": record.get("name")},
            })
    return events


def activity_score(events: list[dict[str, Any]], now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    score = 0
    for event in events:
        try:
            event_time = datetime.fromisoformat(str(event.get("detected_at")).replace("Z", "+00:00"))
            age_days = max(0, (now - event_time).days)
        except (TypeError, ValueError):
            continue
        score += max(1, EVENT_WEIGHTS.get(event.get("type"), 5) - age_days // 30)
    return min(score, 100)


def apply_activity_state(records: list[dict[str, Any]], events: list[dict[str, Any]], observed_ids: set[str]) -> None:
    by_business: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_business.setdefault(event.get("business_id", ""), []).append(event)
    for record in records:
        business_id = record.get("id")
        record["active"] = business_id in observed_ids
        history = by_business.get(business_id, [])
        latest = max(history, key=lambda item: item.get("detected_at", ""), default=None)
        if latest:
            record["activity"] = {"last_event_at": latest.get("detected_at"), "last_event_type": latest.get("type"), "score": activity_score(history)}
