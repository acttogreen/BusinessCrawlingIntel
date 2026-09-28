from datetime import datetime, timezone
from typing import Any
import re


CATEGORY_MAP = {
    "shop": "retail",
    "amenity": "food_and_services",
    "office": "professional_services",
    "craft": "craft_and_manufacturing",
    "tourism": "accommodation_and_tourism",
    "leisure": "leisure_and_sports",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _year(value: Any) -> int | None:
    match = re.search(r"\b(19|20)\d{2}\b", str(value or ""))
    return int(match.group(0)) if match else None


def normalize_element(element: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any] | None:
    tags = element.get("tags") or {}
    name = _clean(tags.get("name") or tags.get("brand") or tags.get("operator"))
    center = element.get("center") or {}
    latitude = element.get("lat", center.get("lat"))
    longitude = element.get("lon", center.get("lon"))
    if not name or latitude is None or longitude is None:
        return None

    osm_type = element.get("type", "unknown")
    osm_id = str(element.get("id"))
    primary_key = next((key for key in CATEGORY_MAP if tags.get(key)), "unknown")
    category = CATEGORY_MAP.get(primary_key, "unknown")
    business_type = _clean(tags.get(primary_key)) or "unknown"
    established_year = _year(tags.get("start_date") or tags.get("opening_date") or tags.get("start_date:opening"))
    now = _now()
    record = {
        "id": f"osm:{osm_type}:{osm_id}",
        "name": name,
        "category": category,
        "subcategory": business_type,
        "business_type": business_type,
        "established_year": established_year,
        "location": {"latitude": float(latitude), "longitude": float(longitude)},
        "address": {
            key: tags[key]
            for key in ("addr:housenumber", "addr:street", "addr:suburb", "addr:city", "addr:postcode")
            if tags.get(key)
        },
        "contact": {
            "phone": _clean(tags.get("phone") or tags.get("contact:phone")),
            "website": _clean(tags.get("website") or tags.get("contact:website")),
            "email": _clean(tags.get("email") or tags.get("contact:email")),
        },
        "source": "openstreetmap",
        "legal": (previous or {}).get("legal", {"status": "unknown"}),
        "investment": (previous or {}).get("investment", {"status": "unknown"}),
        "activity": {},
        "metadata": {
            "osm_type": osm_type,
            "osm_id": element.get("id"),
            "osm_tags": tags,
            "osm_version": element.get("version"),
            "osm_timestamp": element.get("timestamp"),
            "osm_changeset": element.get("changeset"),
            "osm_user": element.get("user"),
            "first_seen_at": (previous or {}).get("metadata", {}).get("first_seen_at", now),
            "last_seen_at": now,
        },
    }
    overrides = (previous or {}).get("metadata", {}).get("manual_overrides", {})
    for key, value in overrides.items():
        if key in record:
            record[key] = value
    if "business_type" in overrides:
        record["subcategory"] = overrides["business_type"]
    return record


def normalize_elements(elements: list[dict[str, Any]], existing: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    by_id = {item.get("id"): item for item in (existing or [])}
    for element in elements:
        record = normalize_element(element, by_id.get(f"osm:{element.get('type', 'unknown')}:{element.get('id')}"))
        if record:
            by_id[record["id"]] = record
    return sorted(by_id.values(), key=lambda item: item.get("name", "").lower())
