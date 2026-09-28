import argparse
from datetime import datetime, timezone

from backend.normalizer import normalize_elements
from backend.overpass import fetch_business_objects
from backend.activity import apply_activity_state, detect_changes
from backend.storage import read_activities, read_businesses, read_metadata, write_activities, write_businesses, write_metadata


def collect(area_name: str = "Surakarta", tags: list[str] | None = None, endpoint: str | None = None, retries: int = 3, timeout_seconds: float | None = None) -> tuple[int, int]:
    elements = fetch_business_objects(endpoint=endpoint, retries=retries, area_name=area_name, tags=tags, timeout_seconds=timeout_seconds)
    previous = read_businesses()
    businesses = normalize_elements(elements, previous)
    observed_ids = {f"osm:{element.get('type', 'unknown')}:{element.get('id')}" for element in elements}
    collected_at = datetime.now(timezone.utc).isoformat()
    activities = read_activities()
    new_events = detect_changes(previous, businesses, observed_ids, collected_at)
    activities.extend(new_events)
    apply_activity_state(businesses, activities, observed_ids)
    write_businesses(businesses)
    metadata = read_metadata()
    metadata.update({
        "source": "openstreetmap",
        "scope": area_name,
        "collected_at": collected_at,
        "raw_object_count": len(elements),
        "normalized_business_count": len(businesses),
        "activity_event_count": len(activities),
        "last_activity_event_count": len(new_events),
    })
    write_activities(activities)
    write_metadata(metadata)
    return len(elements), len(businesses)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect Surakarta business objects from OpenStreetMap")
    parser.add_argument("--area", default="Surakarta", help="OSM administrative area name")
    parser.add_argument("--tag", action="append", help="OSM tag expression, for example shop=supermarket; repeatable")
    parser.add_argument("--endpoint", default=None, help="Overpass interpreter endpoint")
    parser.add_argument("--timeout", type=float, default=None, help="Request timeout in seconds")
    parser.add_argument("--retries", type=int, default=3, help="Number of request attempts")
    args = parser.parse_args()
    raw_count, normalized_count = collect(area_name=args.area, tags=args.tag, endpoint=args.endpoint, retries=args.retries, timeout_seconds=args.timeout)
    print(f"Retrieved OSM objects: {raw_count}")
    print(f"Normalized businesses: {normalized_count}")
