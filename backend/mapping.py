"""Build and read the registry-first business/OSM mapping dataset."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).parent / "data"


def validate_mapping_payload(payload: Any) -> dict[str, Any]:
    """Validate the stable mapping envelope before it is persisted or served."""
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ValueError("business database mapping must use schema_version 1.0")
    businesses = payload.get("businesses")
    if not isinstance(businesses, list):
        raise ValueError("business database mapping businesses must be an array")
    identifiers: set[str] = set()
    for item in businesses:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise ValueError("every mapped business must have a non-empty id")
        if item["id"] in identifiers:
            raise ValueError(f"duplicate mapped business id: {item['id']}")
        identifiers.add(item["id"])
    return payload


def build_mapping_for_sources(registry: list[dict[str, Any]], osm_records: list[dict[str, Any]], registry_name: str, osm_name: str, region_name: str | None = None) -> dict[str, Any]:
    payload = build_mapping(registry, osm_records, region_name=region_name, registry_name=registry_name)
    payload["source_files"] = {"registry": registry_name, "osm": osm_name}
    payload["primary_source"] = registry_name
    payload["region"] = region_name
    return validate_mapping_payload(payload)


DATA_DIR = Path(__file__).parent / "data"
# Legacy pilot files are archived under backend/old_data and are not runtime sources.
# Regional project mappings are the only supported business database source.
OSM_PATH = DATA_DIR / "businesses.json"


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


def _stable_candidate_id(source: dict[str, Any], index: int) -> str:
    identity = "|".join(str(source.get(key, "")).strip().lower() for key in ("company_name", "address", "city", "district"))
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12] if identity.strip("|") else str(index)
    return f"candidate:{digest}"


def _regional_osm_records(records: list[dict[str, Any]], region_name: str | None) -> list[dict[str, Any]]:
    if not region_name:
        return records
    expected = _normalise(region_name).replace("kabupaten ", "").replace("kota ", "")
    scoped = []
    for record in records:
        address = record.get("address", {}) or {}
        values = [address.get("addr:city"), address.get("addr:county"), address.get("addr:municipality")]
        if any(expected and expected in _normalise(value).replace("kabupaten ", "").replace("kota ", "") for value in values):
            scoped.append(record)
    return scoped


def build_mapping(registry: dict[str, Any] | list[dict[str, Any]], osm_records: list[dict[str, Any]], region_name: str | None = None, registry_name: str | None = None) -> dict[str, Any]:
    registry_records = registry if isinstance(registry, list) else registry.get("businesses", [])
    scoped_osm = _regional_osm_records(osm_records, region_name)
    mapped: list[dict[str, Any]] = []
    used_osm_ids: set[str] = set()
    for index, source in enumerate(registry_records, start=1):
        candidates = sorted(
            ((_score(source, item), item) for item in scoped_osm if str(item.get("id")) not in used_osm_ids),
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
        if osm.get("status") == "matched" and osm.get("source_id"):
            used_osm_ids.add(str(osm["source_id"]))
        mapped.append({
            "id": _stable_candidate_id(source, index),
            "name": source.get("company_name"),
            "registry": source,
            "osm": osm,
            "provenance": {
                "primary_source": registry_name or "candidate_registry",
                "mapping_source": "openstreetmap",
                "mapped_at": datetime.now(timezone.utc).isoformat(),
            },
        })
    matched = sum(item["osm"]["status"] == "matched" for item in mapped)
    return {
        "schema_version": "1.0",
        "primary_source": registry_name or "candidate_registry",
        "mapping_source": "openstreetmap",
        "source_files": {"registry": registry_name or "project_candidates", "osm": OSM_PATH.name},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"total": len(mapped), "matched": matched, "unmatched": len(mapped) - matched},
        "businesses": mapped,
    }


def read_mapping() -> dict[str, Any]:
    raise RuntimeError("No default business mapping is configured; select a regional project dataset")


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
            "source": registry.get("source") or "regional_project_dataset",
            "legal": {"status": "known", "entity_type": registry.get("legal_entity")},
            "investment": {"status": "known", "type": registry.get("investment_type")},
            "active": osm.get("status") == "matched",
            "activity": {},
            "metadata": {"osm": osm, "osm_type": osm.get("osm_type"), "osm_id": osm.get("osm_id"), "osm_tags": tags},
            "registry": registry,
            "mapping": {"status": osm.get("status"), "confidence": osm.get("confidence"), "match_method": osm.get("match_method")},
        })
    return records
