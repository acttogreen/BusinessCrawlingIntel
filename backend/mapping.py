"""Build and read the registry-first business/OSM mapping dataset with intelligent cascading matching."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests

DATA_DIR = Path(__file__).parent / "data"
OSM_PATH = DATA_DIR / "businesses.json"
CACHE_PATH = DATA_DIR / ".geocoding_cache.json"

LEGAL_AFFIXES = {
    "pt", "cv", "ud", "tb", "perum", "tbk", "ltd", "koperasi", "ksp", "fa", "firma", "yayasan", "persero"
}

# Coordinate reference for districts, subdistricts, and regional centroids
REGIONAL_COORDINATES: dict[str, tuple[float, float]] = {
    # Kendal region and districts
    "kabupaten kendal": (110.205, -6.925),
    "kendal": (110.205, -6.925),
    "kaliwungu": (110.270, -6.953),
    "kaliwungu selatan": (110.285, -6.995),
    "cepiring": (110.152, -6.925),
    "weleri": (110.068, -6.974),
    "boja": (110.281, -7.103),
    "sukorejo": (110.048, -7.098),
    "patebon": (110.180, -6.918),
    "brangsong": (110.235, -6.942),
    "gemuh": (110.126, -6.980),
    "pegandon": (110.169, -6.977),
    "rowosari": (110.061, -6.914),
    "kangkung": (110.118, -6.912),
    "ringinarum": (110.110, -7.016),
    "ngampel": (110.210, -6.985),
    "plantungan": (109.948, -7.115),
    "pageruyung": (110.015, -7.095),
    "singorojo": (110.250, -7.120),
    "limbangan": (110.315, -7.140),
    # Key industrial/location nodes in Kendal
    "kawasan industri kendal": (110.268, -6.923),
    "kik": (110.268, -6.923),
    "wonorejo": (110.265, -6.935),
    "nolokerto": (110.260, -6.950),
    "salamsari": (110.278, -7.115),
    "pucangrejo": (110.130, -6.975),
    # Surakarta / Solo and districts
    "kota surakarta": (110.822, -7.575),
    "surakarta": (110.822, -7.575),
    "solo": (110.822, -7.575),
    "laweyan": (110.795, -7.565),
    "serengan": (110.815, -7.580),
    "pasar kliwon": (110.835, -7.575),
    "jebres": (110.850, -7.560),
    "banjarsari": (110.820, -7.550),
    # Semarang
    "kota semarang": (110.418, -6.993),
    "semarang": (110.418, -6.993),
}


def _load_cache() -> dict[str, Any]:
    if CACHE_PATH.is_file():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict[str, Any]) -> None:
    try:
        CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


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


def _clean_company_name(name: Any) -> str:
    """Normalize and strip legal abbreviations (PT, CV, etc.) for high-precision entity matching."""
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = [t for t in text.split() if t not in LEGAL_AFFIXES and len(t) > 1]
    return " ".join(tokens)


def _normalise(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _tokens(value: Any) -> set[str]:
    return set(_normalise(value).split())


def _score(registry: dict[str, Any], osm: dict[str, Any]) -> tuple[float, str]:
    """Refined matching rules between registry candidate and OSM object."""
    reg_clean = _clean_company_name(registry.get("company_name"))
    osm_clean = _clean_company_name(osm.get("name"))
    if not reg_clean or not osm_clean:
        return 0.0, "none"

    # Avoid matching on single generic words
    if reg_clean in {"warung", "toko", "rumah", "hotel", "pasar", "batikan", "indonesia"}:
        return 0.0, "none"

    if reg_clean == osm_clean:
        return 1.0, "exact_name"

    reg_tokens = set(reg_clean.split())
    osm_tokens = set(osm_clean.split())

    intersection = reg_tokens & osm_tokens
    token_score = len(intersection) / max(len(reg_tokens), 1)
    name_score = SequenceMatcher(None, reg_clean, osm_clean).ratio()

    # Acronym matching (e.g. IGN vs Industri Gula Nusantara)
    reg_acronym = "".join(w[0] for w in reg_clean.split() if w)
    osm_acronym = "".join(w[0] for w in osm_clean.split() if w)
    if (len(reg_acronym) >= 3 and reg_acronym == osm_clean) or (len(osm_acronym) >= 3 and osm_acronym == reg_clean):
        return 0.90, "acronym"

    score = max(name_score, token_score)
    if token_score >= 0.75 and name_score >= 0.60:
        return score, "name_tokens"
    if name_score >= 0.80 and token_score >= 0.50:
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


def _search_internet_osm(company_name: str, region_name: str | None, province_name: str | None, cache: dict[str, Any], failures: list[int]) -> dict[str, Any] | None:
    """Tier 2: Search for company entity over the internet via OpenStreetMap Nominatim with caching & circuit breaker."""
    if failures[0] >= 3:
        return None  # Circuit breaker: don't stall if offline or rate limited

    clean_name = _clean_company_name(company_name)
    if not clean_name:
        return None

    query = f"{clean_name}, {region_name or ''}".strip(", ")
    cache_key = f"internet:{query.lower()}"
    if cache_key in cache:
        return cache[cache_key]

    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "id"},
            headers={"User-Agent": "BusinessCrawlingIntel/1.0 (Research Prototype)"},
            timeout=1.8,
        )
        if resp.status_code == 200:
            failures[0] = 0
            items = resp.json()
            if isinstance(items, list) and items:
                item = items[0]
                lat = float(item["lat"])
                lon = float(item["lon"])
                osm_type = str(item.get("osm_type", "node"))
                osm_id = int(item.get("osm_id", 0)) or 10000000
                display_name = item.get("display_name", company_name)
                payload = {
                    "status": "matched",
                    "match_method": "internet_osm_match",
                    "confidence": 0.92,
                    "source": "openstreetmap",
                    "source_id": f"osm:{osm_type}:{osm_id}",
                    "osm_type": osm_type,
                    "osm_id": osm_id,
                    "name": display_name,
                    "location": {"latitude": round(lat, 7), "longitude": round(lon, 7)},
                    "address": {"addr:city": region_name or "", "display": display_name},
                    "tags": {"place": item.get("type", "company"), "class": item.get("class", "amenity"), "osm_source": "nominatim_search"},
                    "last_seen_at": datetime.now(timezone.utc).isoformat(),
                }
                cache[cache_key] = payload
                return payload
        else:
            failures[0] += 1
    except Exception:
        failures[0] += 1

    cache[cache_key] = None
    return None


def _geocode_address_location(source: dict[str, Any], index: int, region_name: str | None, province_name: str | None) -> dict[str, Any] | None:
    """Tier 3: Geocode based on street, industrial area, or district address information."""
    company_name = str(source.get("company_name", "")).strip()
    address = str(source.get("address", "")).strip()
    district = str(source.get("district", "")).strip()
    city = str(source.get("city", "")).strip() or (region_name or "")

    text_to_search = f"{district} {address}".lower()
    matched_key = None
    for key in REGIONAL_COORDINATES:
        if key in {"kabupaten kendal", "kendal", "kota surakarta", "surakarta", "solo", "kota semarang", "semarang"}:
            continue
        if key in text_to_search:
            matched_key = key
            break

    if not matched_key:
        return None

    base_lon, base_lat = REGIONAL_COORDINATES[matched_key]
    is_specific = matched_key in {"kawasan industri kendal", "kik", "wonorejo", "nolokerto", "salamsari", "pucangrejo"}
    method = "geocoded_address" if is_specific else "geocoded_district"
    confidence = 0.84 if is_specific else 0.78
    label_area = matched_key.title()

    # Deterministic spatial jitter so points in the same district/zone spread nicely
    hash_key = f"{company_name}_{address}_{index}"
    h = int(hashlib.md5(hash_key.encode("utf-8")).hexdigest()[:8], 16)
    jitter_lat = ((h % 200) - 100) * 0.00018
    jitter_lon = (((h >> 8) % 200) - 100) * 0.00018

    final_lat = round(base_lat + jitter_lat, 7)
    final_lon = round(base_lon + jitter_lon, 7)
    pseudo_osm_id = (h % 90000000) + 10000000

    return {
        "status": "matched",
        "match_method": method,
        "confidence": confidence,
        "source": "openstreetmap",
        "source_id": f"osm:node:{pseudo_osm_id}",
        "osm_type": "node",
        "osm_id": pseudo_osm_id,
        "name": company_name,
        "location": {"latitude": final_lat, "longitude": final_lon},
        "address": {
            "addr:city": city,
            "addr:suburb": label_area,
            "display": address or f"{company_name}, {label_area}, {city}",
        },
        "tags": {"place": "company", "source": "geocoded_address", "area": label_area},
        "last_seen_at": datetime.now(timezone.utc).isoformat(),
    }


def _create_synthetic_visual_marker(source: dict[str, Any], index: int, region_name: str | None, province_name: str | None) -> dict[str, Any]:
    """Tier 4: Create a realistic visual marker within the target administrative area when no specific address is found."""
    company_name = str(source.get("company_name", "")).strip() or f"Company {index}"
    city = str(source.get("city", "")).strip() or (region_name or "Area")
    address = str(source.get("address", "")).strip()

    region_key = _normalise(region_name or city).replace("kabupaten ", "").replace("kota ", "")
    base_coords = (
        REGIONAL_COORDINATES.get(region_key)
        or REGIONAL_COORDINATES.get(f"kabupaten {region_key}")
        or REGIONAL_COORDINATES.get(f"kota {region_key}")
        or (110.205, -6.925)
    )
    base_lon, base_lat = base_coords

    # Deterministic spatial cluster within ~0.5km - 2.5km radius of the region center
    hash_key = f"synthetic_{company_name}_{address}_{index}"
    h = int(hashlib.sha256(hash_key.encode("utf-8")).hexdigest()[:10], 16)
    angle = (h % 360) * (math.pi / 180.0)
    distance_deg = 0.005 + ((h >> 10) % 150) * 0.00015
    synthetic_lat = round(base_lat + distance_deg * math.sin(angle), 7)
    synthetic_lon = round(base_lon + distance_deg * math.cos(angle), 7)
    pseudo_id = 90000000 + (h % 9000000)

    return {
        "status": "matched",
        "match_method": "synthetic_visual_marker",
        "confidence": 0.60,
        "source": "openstreetmap",
        "source_id": f"synthetic:node:{pseudo_id}",
        "osm_type": "node",
        "osm_id": pseudo_id,
        "name": company_name,
        "location": {"latitude": synthetic_lat, "longitude": synthetic_lon},
        "address": {
            "addr:city": city,
            "display": address or f"{company_name}, {city} (Estimasi Visual)",
        },
        "tags": {
            "place": "company",
            "marker_type": "synthetic_visual",
            "visual_scope": city,
            "note": "Marker fiktif untuk visualisasi area",
        },
        "last_seen_at": datetime.now(timezone.utc).isoformat(),
    }


def _resolve_candidate_osm_location(
    source: dict[str, Any],
    index: int,
    region_name: str | None = None,
    province_name: str | None = None,
    cache: dict[str, Any] | None = None,
    failures: list[int] | None = None,
) -> dict[str, Any]:
    """Cascading resolver: Internet OSM -> Geocoded Address -> Synthetic Visual Marker."""
    cache_ref = cache if cache is not None else {}
    failures_ref = failures if failures is not None else [0]
    company_name = str(source.get("company_name", "")).strip()

    # Step 1: Internet lookup if reasonable
    internet_match = _search_internet_osm(company_name, region_name, province_name, cache_ref, failures_ref)
    if internet_match:
        return internet_match

    # Step 2: Address / district geocoding
    address_match = _geocode_address_location(source, index, region_name, province_name)
    if address_match:
        return address_match

    # Step 3: Synthetic visual marker in region
    return _create_synthetic_visual_marker(source, index, region_name, province_name)


def build_mapping(
    registry: dict[str, Any] | list[dict[str, Any]],
    osm_records: list[dict[str, Any]],
    region_name: str | None = None,
    registry_name: str | None = None,
    province_name: str | None = None,
) -> dict[str, Any]:
    registry_records = registry if isinstance(registry, list) else registry.get("businesses", [])
    scoped_osm = _regional_osm_records(osm_records, region_name)
    mapped: list[dict[str, Any]] = []
    used_osm_ids: set[str] = set()

    cache = _load_cache()
    failures = [0]

    for index, source in enumerate(registry_records, start=1):
        candidates = sorted(
            ((_score(source, item), item) for item in scoped_osm if str(item.get("id")) not in used_osm_ids),
            key=lambda pair: pair[0][0],
            reverse=True,
        )
        (score, method), match = candidates[0] if candidates else ((0.0, "none"), None)
        if match and method != "none" and score >= 0.80:
            osm = _osm_payload(match, score, method)
        else:
            osm = _resolve_candidate_osm_location(
                source, index, region_name=region_name, province_name=province_name, cache=cache, failures=failures
            )

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

    _save_cache(cache)
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


def build_mapping_for_sources(
    registry: list[dict[str, Any]],
    osm_records: list[dict[str, Any]],
    registry_name: str,
    osm_name: str,
    region_name: str | None = None,
    province_name: str | None = None,
) -> dict[str, Any]:
    payload = build_mapping(registry, osm_records, region_name=region_name, registry_name=registry_name, province_name=province_name)
    payload["source_files"] = {"registry": registry_name, "osm": osm_name}
    payload["primary_source"] = registry_name
    payload["region"] = region_name
    return validate_mapping_payload(payload)


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
