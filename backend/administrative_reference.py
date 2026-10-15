"""Validated Emsifa Indonesia administrative reference with local snapshot fallback."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Callable

import requests

BASE_URL = "https://www.emsifa.com/api-wilayah-indonesia/v2"
ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "administrative_reference.json"
TIMEOUT = (5, 20)

@dataclass(frozen=True)
class Province:
    id: str
    name: str

@dataclass(frozen=True)
class Region:
    id: str
    name: str
    province_id: str


def _validate_items(payload: Any, level: int, province_id: str | None = None) -> list[dict[str, str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Emsifa response must contain an array data property")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in payload["data"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip() or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError("Emsifa record has invalid id or name")
        item_id = item["id"].strip()
        if item_id in seen:
            raise ValueError(f"duplicate administrative id: {item_id}")
        if level == 2 and (not province_id or not item_id.startswith(province_id + ".")):
            raise ValueError(f"region {item_id} does not belong to province {province_id}")
        seen.add(item_id)
        result.append({"id": item_id, "name": item["name"].strip()})
    if not result:
        raise ValueError("Emsifa returned an empty dataset")
    return result


def validate_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    provinces = _validate_items({"data": data.get("provinces")}, 1)
    regions: list[dict[str, str]] = []
    for item in data.get("regions", []):
        if not isinstance(item, dict):
            raise ValueError("invalid cached region")
        regions.append({"id": item["id"], "name": item["name"], "province_id": item["province_id"]})
    if not regions:
        raise ValueError("cached snapshot has no regions")
    _validate_items({"data": [{"id": x["id"], "name": x["name"]} for x in regions]}, 2, None) if False else None
    province_ids = {x["id"] for x in provinces}
    region_ids: set[str] = set()
    for item in regions:
        if item["province_id"] not in province_ids or not item["id"].startswith(item["province_id"] + ".") or item["id"] in region_ids:
            raise ValueError("invalid cached province-region relationship")
        region_ids.add(item["id"])
    return {"provinces": provinces, "regions": regions, "metadata": data.get("metadata", {})}


def _load() -> dict[str, Any]:
    return validate_snapshot(json.loads(DATA_PATH.read_text(encoding="utf-8-sig")))


def sync_reference(fetcher: Callable[[str], dict[str, Any]] | None = None) -> dict[str, Any]:
    fetch = fetcher or _fetch
    provinces_payload = fetch(f"{BASE_URL}/provinces.json")
    provinces = _validate_items(provinces_payload, 1)
    regions: list[dict[str, str]] = []
    for item in provinces:
        payload = fetch(f"{BASE_URL}/regencies/{item['id']}.json")
        for region_item in _validate_items(payload, 2, item["id"]):
            regions.append({**region_item, "province_id": item["id"]})
    snapshot = validate_snapshot({"provinces": provinces, "regions": regions, "metadata": {"source_url": BASE_URL, "synchronized_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(), "province_count": len(provinces), "region_count": len(regions), "status": "success"}})
    temporary = DATA_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(DATA_PATH)
    return snapshot


def _fetch(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Emsifa response is not an object")
    return payload

_DATA = _load()
PROVINCES = tuple(Province(x["id"], x["name"]) for x in _DATA["provinces"])
REGIONS = tuple(Region(x["id"], x["name"], x["province_id"]) for x in _DATA["regions"])
METADATA = _DATA["metadata"]

def province(code: str) -> Province | None:
    return next((x for x in PROVINCES if x.id == code), None)

def region(code: str) -> Region | None:
    return next((x for x in REGIONS if x.id == code), None)

def validate_pair(province_id: str, region_id: str) -> tuple[Province, Region]:
    selected_province, selected_region = province(province_id), region(region_id)
    if not selected_province or not selected_region or selected_region.province_id != selected_province.id:
        raise ValueError("province and regency/city IDs are invalid or do not belong together")
    return selected_province, selected_region

def province_payload(item: Province) -> dict[str, str]:
    return asdict(item)

def region_payload(item: Region) -> dict[str, str]:
    return asdict(item)

