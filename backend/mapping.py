"""Build and read the registry-first business/OSM mapping dataset."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).parent / "data"
REGISTRY_PATH = DATA_DIR / "Business_database_5.0.json"
OSM_PATH = DATA_DIR / "businesses.json"
MAPPING_PATH = DATA_DIR / "business_database_mapping.json"


def _normalise(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _tokens(value: Any) -> set[str]:
    return set(_normalise(value).split())


def _score(registry: dict[str, Any], osm: dict[str, Any]) -> tuple[float, str]:
    registry_name = _normalise(registry.get("company_name"))
    osm_name = _normalise(osm.get("name"))
    if not registry_name or not osm_name:
        return 0.0, "none"
    # A one-word generic label is not enough evidence for an entity match.
    if registry_name in {"warung", "toko", "rumah", "hotel", "pasar", "batikan"}:
        return 0.0, "none"
    name_score = SequenceMatcher(None, registry_name, osm_name).ratio()
    registry_tokens = _tokens(registry_name)
    osm_tokens = _tokens(osm_name)
    token_score = len(registry_tokens & osm_tokens) / max(len(registry_tokens), 1)
    score = max(name_score, token_score)
    if registry_name == osm_name:
        return 1.0, "exact_name"
    if token_score >= 0.8 and name_score >= 0.65:
        return score, "name_tokens"
    if name_score >= 0.82 and token_score >= 0.6:
        return score, "name_similarity"
    return score, "none"


def _osm_payload(record: dict[str, Any], score: float, method: str) -> dict[str, Any]:
    metadata = record.get("metadata", {})
    return {
        "status": "matched",
        "match_method": method,
        "confidence": round(score, 3),
        "source": "openstreetmap",
        "source_id": record.get("id"),
        "osm_type": metadata.get("osm_type"),
        "osm_id": metadata.get("osm_id"),
        "name": record.get("name"),
        "location": record.get("location"),
        "address": record.get("address", {}),
        "tags": metadata.get("osm_tags", {}),
        "last_seen_at": metadata.get("last_seen_at"),
    }


def build_mapping(registry: dict[str, Any] | list[dict[str, Any]], osm_records: list[dict[str, Any]]) -> dict[str, Any]:
    registry_records = registry if isinstance(registry, list) else registry.get("businesses", [])
    mapped: list[dict[str, Any]] = []
    for index, source in enumerate(registry_records, start=1):
        candidates = sorted(
            ((_score(source, item), item) for item in osm_records),
            key=lambda pair: pair[0][0],
            reverse=True,
        )
        (score, method), match = candidates[0] if candidates else ((0.0, "none"), None)
        osm = _osm_payload(match, score, method) if match and method != "none" and score >= 0.82 else {
            "status": "unmatched",
            "match_method": "none",
            "confidence": round(score, 3),
            "source": "openstreetmap",
        }
        mapped.append({
            "id": f"registry:{index}",
            "name": source.get("company_name"),
            "registry": source,
            "osm": osm,
            "provenance": {
                "primary_source": "Business_database_5.0",
                "mapping_source": "openstreetmap",
                "mapped_at": datetime.now(timezone.utc).isoformat(),
            },
        })
    matched = sum(item["osm"]["status"] == "matched" for item in mapped)
    return {
        "schema_version": "1.0",
        "primary_source": "Business_database_5.0",
        "mapping_source": "openstreetmap",
        "source_files": {"registry": REGISTRY_PATH.name, "osm": OSM_PATH.name},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"total": len(mapped), "matched": matched, "unmatched": len(mapped) - matched},
        "businesses": mapped,
    }


def read_mapping() -> dict[str, Any]:
    if not MAPPING_PATH.exists():
        return build_mapping(json.loads(REGISTRY_PATH.read_text(encoding="utf-8")), json.loads(OSM_PATH.read_text(encoding="utf-8")))
    return json.loads(MAPPING_PATH.read_text(encoding="utf-8"))


def mapped_businesses(mapping: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    records = []
    for item in (mapping or read_mapping()).get("businesses", []):
        registry = item.get("registry", {})
        osm = item.get("osm", {})
        location = osm.get("location") or {"latitude": None, "longitude": None}
        tags = osm.get("tags", {})
        category = registry.get("business_sector") or "unknown"
        records.append({
            "id": item["id"],
            "name": item.get("name") or registry.get("company_name") or "Unknown",
            "category": category,
            "subcategory": category,
            "business_type": category,
            "established_year": None,
            "location": location,
            "address": {"addr:suburb": registry.get("district"), "addr:city": registry.get("city"), "display": registry.get("address")},
            "contact": {"phone": registry.get("phone") or registry.get("phone_number"), "email": registry.get("email"), "website": registry.get("website")},
            "source": "Business_database_5.0",
            "legal": {"status": "known", "entity_type": registry.get("legal_entity")},
            "investment": {"status": "known", "type": registry.get("investment_type")},
            "active": osm.get("status") == "matched",
            "activity": {},
            "metadata": {"osm": osm, "osm_type": osm.get("osm_type"), "osm_id": osm.get("osm_id"), "osm_tags": tags},
            "registry": registry,
            "mapping": {"status": osm.get("status"), "confidence": osm.get("confidence"), "match_method": osm.get("match_method")},
        })
    return records
