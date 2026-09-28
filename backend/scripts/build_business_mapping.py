"""Generate the Business_database_5.0-first OSM mapping JSON.

Usage: python -m backend.scripts.build_business_mapping
"""

import json

from backend.mapping import MAPPING_PATH, OSM_PATH, REGISTRY_PATH, build_mapping


def main() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    osm_records = json.loads(OSM_PATH.read_text(encoding="utf-8"))
    mapping = build_mapping(registry, osm_records)
    MAPPING_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mapped {mapping['summary']['matched']}/{mapping['summary']['total']} registry records")


if __name__ == "__main__":
    main()
