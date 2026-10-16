import csv
import io
import json
import zipfile
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

from pathlib import Path

from backend.administrative_reference import METADATA, PROVINCES, REGIONS, province, region, province_payload, region_payload, sync_reference
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from backend.pdf_ingestion import add_document, create_project, delete_document, delete_project, get_document, get_project, project_path, public_document, queue_document, read_state, write_state, document_path
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.storage import read_activities, read_businesses, read_metadata
from backend.mapping import build_mapping_for_sources, validate_mapping_payload


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _region_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def region_mapping_path(project: dict[str, Any]) -> Path:
    # Region datasets live under backend/data and are keyed by validated names,
    # not by user-supplied dropdown labels or project IDs. Existing datasets may
    # omit the administrative prefix (e.g. kota_surakarta -> surakarta).
    data_root = Path(__file__).parent / "data"
    province_name, region_name = project["province_name"], project["region_name"]
    province_dir = data_root / _region_slug(province_name)
    region_slug = _region_slug(region_name)
    candidates = [region_slug]
    for prefix in ("kabupaten_", "kota_"):
        if region_slug.startswith(prefix):
            candidates.append(region_slug[len(prefix):])
    for candidate in candidates:
        path = province_dir / candidate / "business_database_mapping.json"
        if path.exists():
            return path
    return province_dir / region_slug / "business_database_mapping.json"
from backend.preferences import preferences_status, read_preferences, write_preferences
from backend.ai_curation import curation_status, load_and_curate, preference_error


app = FastAPI(title="Surakarta Business Intelligence API", version="0.1.0")


@app.get("/api/preferences", response_model=dict[str, Any])
def get_preferences() -> dict[str, Any]:
    settings = read_preferences()
    if not settings:
        settings = {"provider": "openai", "model": "gpt-4o-mini", "endpoint": "https://api.openai.com/v1", "batch_size": 20, "timeout_seconds": 180, "retry_count": 2, "confidence": 0.75, "ruleset": "", "web_lookup": False, "token": ""}
    return {
        "configured": bool(settings.get("token")) or settings.get("provider") in {"ollama", "local"},
        "provider": settings["provider"],
        "model": settings["model"],
        "endpoint": settings["endpoint"],
        "batch_size": settings["batch_size"],
        "timeout_seconds": settings.get("timeout_seconds", 180),
        "retry_count": settings.get("retry_count", 2),
        "confidence": settings["confidence"],
        "ruleset": settings.get("ruleset", ""),
        "web_lookup": settings.get("web_lookup", False),
        "token_configured": bool(settings.get("token")),
    }



class PreferencesInput(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    model: str = Field(default="", max_length=200)
    token: str = Field(default="", max_length=1000)
    endpoint: str = Field(default="", max_length=500)
    batch_size: int = Field(default=20, ge=1, le=200)
    timeout_seconds: int = Field(default=180, ge=30, le=600)
    retry_count: int = Field(default=2, ge=0, le=5)
    confidence: float = Field(default=0.75, ge=0, le=1)
    ruleset: str = Field(default="", max_length=12000)
    web_lookup: bool = False
    mapping: dict[str, Any]


class TokenCheckInput(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    token: str = Field(default="", max_length=1000)
    endpoint: str = Field(default="", max_length=500)


@app.get("/api/preferences/status")
def preference_status() -> dict[str, Any]:
    return preferences_status()


@app.post("/api/preferences/check-token")
def check_preference_token(payload: TokenCheckInput) -> dict[str, Any]:
    provider = payload.provider.lower().strip()
    base_urls = {"openai": "https://api.openai.com/v1", "groq": "https://api.groq.com/openai/v1", "together": "https://api.together.xyz/v1", "ollama": "http://127.0.0.1:11434/v1", "local": "http://127.0.0.1:11434/v1"}
    base_url = payload.endpoint.strip().rstrip("/") if payload.endpoint.strip() else base_urls.get(provider)
    if not base_url or provider == "anthropic":
        raise HTTPException(status_code=400, detail="Provider tidak didukung atau endpoint belum diisi")
    headers = {"Authorization": f"Bearer {payload.token.strip()}"} if payload.token.strip() else {}
    try:
        for suffix in ("/chat/completions", "/models"):
            if base_url.lower().endswith(suffix):
                base_url = base_url[:-len(suffix)].rstrip("/")
        if not base_url.lower().endswith("/v1") and provider in {"openai", "groq", "together"}:
            base_url = f"{base_url}/v1"
        response = requests.get(f"{base_url}/models", headers=headers, timeout=15)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Provider tidak dapat dihubungi") from exc
    if response.ok:
        return {"connected": True, "provider": provider, "message": "Token valid dan provider dapat dihubungi"}
    if response.status_code in {401, 403}:
        return {"connected": False, "provider": provider, "message": "Token ditolak oleh provider"}
    return {"connected": False, "provider": provider, "message": f"Provider merespons HTTP {response.status_code}"}


@app.get("/api/preferences/curation-status")
def preference_curation_status() -> dict[str, Any]:
    error = preference_error()
    if error:
        return {"connected": False, "configured": False, "message": error}
    try:
        return curation_status()
    except requests.RequestException:
        settings = read_preferences() or {}
        return {"connected": False, "configured": True, "provider": settings.get("provider"), "model": settings.get("model"), "message": "Provider AI tidak dapat dihubungi."}
    except RuntimeError as exc:
        return {"connected": False, "configured": True, "message": str(exc)}


@app.post("/api/preferences")
def save_preferences(payload: PreferencesInput) -> dict[str, Any]:
    settings = payload.model_dump()
    settings["provider"] = settings["provider"].strip().lower()
    settings["endpoint"] = settings["endpoint"].strip().rstrip("/")
    settings["model"] = settings["model"].strip()
    existing = read_preferences() or {}
    if not settings["model"]:
        settings["model"] = str(existing.get("model", "")).strip()
    if not settings["endpoint"]:
        settings["endpoint"] = str(existing.get("endpoint", "")).strip()
    if not settings["model"]:
        if not settings["endpoint"]:
            raise HTTPException(status_code=422, detail="Endpoint wajib diisi jika model dikosongkan")
        base_url = settings["endpoint"]
        for suffix in ("/chat/completions", "/models"):
            if base_url.lower().endswith(suffix):
                base_url = base_url[:-len(suffix)].rstrip("/")
        try:
            headers = {"Authorization": f"Bearer {settings['token'].strip()}"} if settings.get("token", "").strip() else {}
            response = requests.get(f"{base_url}/models", headers=headers, timeout=15)
            response.raise_for_status()
            models = response.json().get("data", [])
            model_ids = [item.get("id") for item in models if isinstance(item, dict) and str(item.get("id", "")).strip()]
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise HTTPException(status_code=502, detail="Model kosong dan daftar model 9Router tidak dapat dibaca") from exc
        if not model_ids:
            raise HTTPException(status_code=502, detail="Model kosong dan 9Router tidak mengembalikan model tersedia")
        settings["model"] = model_ids[0]
    try:
        write_preferences(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"saved": True, "model": settings["model"], **preferences_status()}


@app.post("/api/refresh")
def refresh_osm() -> None:
    raise HTTPException(status_code=405, detail="OSM refresh is disabled on the public API")


@app.get("/api/refresh/status")
def refresh_status() -> dict[str, Any]:
    return {"status": "disabled"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/businesses")
def businesses(category: str | None = Query(default=None), district: str | None = Query(default=None), business_type: str | None = Query(default=None), established_year: str | None = Query(default=None), investment_type: str | None = Query(default=None), legal_entity: str | None = Query(default=None), mapping_status: str | None = Query(default=None), activity_days: int | None = Query(default=None, ge=1), activity_type: str | None = Query(default=None)) -> dict[str, Any]:
    records = filter_businesses(read_businesses(), category, district, business_type, established_year, investment_type, legal_entity, mapping_status, activity_days=activity_days, activity_type=activity_type)
    return {"businesses": records, "total": len(records)}


def filter_businesses(records: list[dict[str, Any]], category: str | None = None, district: str | None = None, business_type: str | None = None, established_year: str | None = None, investment_type: str | None = None, legal_entity: str | None = None, mapping_status: str | None = None, query: str | None = None, activity_days: int | None = None, activity_type: str | None = None) -> list[dict[str, Any]]:
    if category and category != "all":
        records = [record for record in records if record.get("category") == category]
    if district:
        records = [record for record in records if record.get("address", {}).get("addr:suburb") == district]
    if business_type and business_type != "all":
        records = [record for record in records if record.get("business_type", record.get("subcategory")) == business_type]
    if investment_type and investment_type != "all":
        records = [record for record in records if record.get("investment", {}).get("type") == investment_type]
    if legal_entity and legal_entity != "all":
        records = [record for record in records if record.get("legal", {}).get("entity_type") == legal_entity]
    if mapping_status and mapping_status != "all":
        records = [record for record in records if record.get("mapping", {}).get("status") == mapping_status]
    if established_year is not None:
        if established_year == "unknown":
            records = [record for record in records if not record.get("established_year")]
        elif established_year.isdigit():
            records = [record for record in records if record.get("established_year") == int(established_year)]
        else:
            records = []
    if query:
        needle = query.strip().lower()
        records = [record for record in records if needle in record.get("name", "").lower() or needle in record.get("id", "").lower()]
    if activity_type and activity_type != "all":
        records = [record for record in records if record.get("activity", {}).get("last_event_type") == activity_type]
    if activity_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=activity_days)
        records = [record for record in records if _activity_datetime(record) and _activity_datetime(record) >= cutoff]
    return records


def _activity_datetime(record: dict[str, Any]) -> datetime | None:
    value = record.get("activity", {}).get("last_event_at")
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


EXPORT_COLUMNS = ["id", "name", "category", "business_type", "legal_entity", "investment_type", "mapping_status", "latitude", "longitude", "address", "source", "osm_type", "osm_id"]
EXPORT_HEADERS = ["ID", "Name", "Sector", "Business Type", "Legal Entity", "Investment Type", "OSM Mapping", "Latitude", "Longitude", "Address", "Source", "OSM Type", "OSM ID"]


def export_rows(records: list[dict[str, Any]]) -> list[list[Any]]:
    rows = []
    for record in records:
        address = record.get("address", {})
        contact = record.get("contact", {})
        metadata = record.get("metadata", {})
        osm = metadata.get("osm", {})
        rows.append([
            record.get("id", ""), record.get("name", ""), record.get("category", ""), record.get("business_type", record.get("subcategory", "")),
            record.get("legal", {}).get("entity_type", ""), record.get("investment", {}).get("type", ""), record.get("mapping", {}).get("status", ""),
            record.get("location", {}).get("latitude") or "", record.get("location", {}).get("longitude") or "",
            " ".join(str(address[key]) for key in ("addr:housenumber", "addr:street", "addr:suburb", "addr:city", "addr:postcode") if address.get(key)),
            record.get("source", ""), osm.get("osm_type", metadata.get("osm_type", "")), osm.get("osm_id", metadata.get("osm_id", "")),
        ])
    return rows


def export_filter_params(category: str | None, district: str | None, business_type: str | None, established_year: str | None, query: str | None, investment_type: str | None = None, legal_entity: str | None = None) -> list[dict[str, Any]]:
    return export_rows(filter_businesses(read_businesses(), category, district, business_type, established_year, investment_type, legal_entity, query=query))


@app.get("/api/export.csv")
def export_csv(category: str | None = None, district: str | None = None, business_type: str | None = None, established_year: str | None = None, investment_type: str | None = None, legal_entity: str | None = None, q: str | None = None) -> Response:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(EXPORT_HEADERS)
    writer.writerows(export_filter_params(category, district, business_type, established_year, q, investment_type, legal_entity))
    return Response(content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=surakarta-businesses.csv"})


def xml_text(value: Any) -> str:
    import xml.sax.saxutils as saxutils
    text = str(value if value is not None else "")
    text = "".join(character for character in text if character in "\t\n\r" or ord(character) >= 32)
    return saxutils.escape(text)


def xlsx_cell(reference: str, value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{reference}"><v>{value}</v></c>'
    return f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">{xml_text(value)}</t></is></c>'


def build_xlsx(rows: list[list[Any]]) -> bytes:
    all_rows = [EXPORT_HEADERS, *rows]
    sheet_rows = []
    for row_number, row in enumerate(all_rows, start=1):
        cells = []
        for column_number, value in enumerate(row, start=1):
            column = ""
            number = column_number
            while number:
                number, remainder = divmod(number - 1, 26)
                column = chr(65 + remainder) + column
            cells.append(xlsx_cell(f"{column}{row_number}", value))
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Businesses" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>',
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as workbook:
        for path, content in files.items():
            workbook.writestr(path, content)
    return output.getvalue()


@app.get("/api/export.xlsx")
def export_xlsx(category: str | None = None, district: str | None = None, business_type: str | None = None, established_year: str | None = None, investment_type: str | None = None, legal_entity: str | None = None, q: str | None = None) -> Response:
    content = build_xlsx(export_filter_params(category, district, business_type, established_year, q, investment_type, legal_entity))
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=surakarta-businesses.xlsx"})


@app.get("/api/categories")
def categories() -> dict[str, Any]:
    records = read_businesses()
    values = {record.get("category", "unknown") for record in records}
    custom = read_metadata().get("custom_categories", [])
    return {"categories": [{"id": value, "name": value.replace("_", " ").title(), "custom": False} for value in sorted(values)] + [{**item, "custom": True} for item in custom]}


@app.post("/api/categories")
def create_category() -> None:
    raise HTTPException(status_code=405, detail="Category changes are disabled on the public API")


@app.get("/api/businesses/{business_id}")
def business(business_id: str) -> dict[str, Any]:
    record = next((item for item in read_businesses() if item.get("id") == business_id), None)
    if not record:
        raise HTTPException(status_code=404, detail="Business not found")
    return record


@app.patch("/api/businesses/{business_id}")
def update_business(business_id: str) -> None:
    raise HTTPException(status_code=405, detail="Business changes are disabled on the public API")


@app.get("/api/businesses/{business_id}/activities")
def business_activities(business_id: str) -> dict[str, Any]:
    return {"business_id": business_id, "activities": [item for item in read_activities() if item.get("business_id") == business_id]}


@app.get("/api/activity-summary")
def activity_summary() -> dict[str, Any]:
    events = read_activities()
    counts: dict[str, int] = {}
    for event in events:
        event_type = event.get("type", "unknown")
        counts[event_type] = counts.get(event_type, 0) + 1
    return {"total_events": len(events), "by_type": counts, "recent_events": sorted(events, key=lambda item: item.get("detected_at", ""), reverse=True)[:20]}


@app.get("/api/statistics")
def statistics() -> dict[str, Any]:
    records = read_businesses()
    categories: dict[str, int] = {}
    for record in records:
        key = record.get("category", "unknown")
        categories[key] = categories.get(key, 0) + 1
    return {"total_businesses": len(records), "categories": categories}


@app.get("/api/metadata")
def metadata() -> dict[str, Any]:
    return read_metadata()


class IngestionProjectInput(BaseModel):
    province_code: str = Field(min_length=1, max_length=3)
    province_name: str = Field(min_length=1, max_length=200)
    regency_code: str = Field(min_length=4, max_length=12)
    regency_name: str = Field(min_length=1, max_length=200)
    source_year: int | None = Field(default=None, ge=1900, le=2200)
    description: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)


@app.get("/api/administrative/metadata")
def administrative_metadata() -> dict[str, Any]:
    return METADATA

@app.post("/api/administrative/sync")
def administrative_sync() -> dict[str, Any]:
    try:
        snapshot = sync_reference()
        return {"status": "success", "metadata": snapshot["metadata"]}
    except Exception as exc:
        raise HTTPException(502, f"Sinkronisasi wilayah gagal: {exc}") from exc

REGION_MAP_FALLBACKS: dict[str, tuple[float, float]] = {
    "Kabupaten Kendal": (110.205, -6.925),
    "Kota Surakarta": (110.822, -7.575),
}


def _regional_map_center(mapping_path: Path, region_name: str) -> list[float]:
    """Return [longitude, latitude] from matched OSM records, with explicit regional fallback."""
    try:
        payload = json.loads(mapping_path.read_text(encoding="utf-8-sig"))
        locations = [
            item.get("osm", {}).get("location", {})
            for item in payload.get("businesses", [])
            if item.get("osm", {}).get("status") == "matched"
        ]
        coordinates = [
            (float(location["longitude"]), float(location["latitude"]))
            for location in locations
            if isinstance(location, dict) and location.get("longitude") is not None and location.get("latitude") is not None
        ]
        if coordinates:
            return [sum(point[0] for point in coordinates) / len(coordinates), sum(point[1] for point in coordinates) / len(coordinates)]
    except (OSError, ValueError, TypeError, KeyError):
        pass
    fallback = REGION_MAP_FALLBACKS.get(region_name)
    if fallback:
        return [fallback[0], fallback[1]]
    return [0.0, 0.0]


@app.get("/api/data/regions")
def available_data_regions() -> dict[str, Any]:
    """List only regional folders that contain a usable mapping JSON file."""
    data_root = Path(__file__).parent / "data"
    items: list[dict[str, Any]] = []
    for province_dir in sorted(data_root.iterdir()):
        if not province_dir.is_dir() or province_dir.name == "extracted_artifacts":
            continue
        province_item = next((item for item in PROVINCES if _region_slug(item.name) == province_dir.name), None)
        for region_dir in sorted(province_dir.iterdir()):
            mapping_path = region_dir / "business_database_mapping.json"
            if not region_dir.is_dir() or not mapping_path.is_file():
                continue
            region_item = next((item for item in REGIONS if item.province_id == (province_item.id if province_item else "") and _region_slug(item.name) in {region_dir.name, f"kota_{region_dir.name}", f"kabupaten_{region_dir.name}"}), None)
            if not province_item or not region_item:
                continue
            center = _regional_map_center(mapping_path, region_item.name)
            items.append({"province_code": province_item.id, "province_name": province_item.name, "province_slug": province_dir.name, "region_code": region_item.id, "region_name": region_item.name, "region_slug": region_dir.name, "center": center, "zoom": 10})
    return {"data": items}

@app.get("/api/administrative/provinces")
def administrative_provinces() -> dict[str, Any]:
    return {"data": [province_payload(item) for item in PROVINCES], "metadata": METADATA}

@app.get("/api/administrative/provinces/{province_code}/regions")
def administrative_regions(province_code: str) -> dict[str, Any]:
    if not province(province_code):
        raise HTTPException(404, "Kode provinsi tidak ditemukan")
    return {"data": [region_payload(item) for item in REGIONS if item.province_id == province_code], "metadata": METADATA}

@app.get("/api/administrative/provinces/{province_code}")
def administrative_province(province_code: str) -> dict[str, Any]:
    item = province(province_code)
    if not item:
        raise HTTPException(404, "Kode provinsi tidak ditemukan")
    return {"data": province_payload(item), "metadata": METADATA}

@app.get("/api/administrative/regions/{region_code}")
def administrative_region(region_code: str) -> dict[str, Any]:
    item = region(region_code)
    if not item:
        raise HTTPException(404, "Kode kabupaten/kota tidak ditemukan")
    return {"data": region_payload(item), "metadata": METADATA}


@app.get("/api/administrative/regions/{region_code}/districts")
def administrative_districts(region_code: str) -> dict[str, Any]:
    if not region(region_code):
        raise HTTPException(404, "Kode kabupaten/kota tidak ditemukan")
    try:
        response = requests.get(f"https://www.emsifa.com/api-wilayah-indonesia/v2/districts/{region_code}.json", timeout=(5, 20))
        response.raise_for_status()
        payload = response.json()
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ValueError("format data kecamatan tidak valid")
        districts = [{"id": item["id"].strip(), "name": item["name"].strip(), "region_id": region_code} for item in items if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip() and isinstance(item.get("name"), str) and item["name"].strip()]
        if not districts:
            raise ValueError("data kecamatan kosong")
        return {"data": districts, "metadata": METADATA}
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise HTTPException(502, f"Data kecamatan tidak tersedia: {exc}") from exc


@app.get("/api/ingestion/projects")
def ingestion_projects() -> dict[str, Any]:
    state = read_state()
    projects = []
    for project in state["projects"]:
        project = dict(project); project["documents"] = [public_document(d) for d in state["documents"] if d["project_id"] == project["id"]]; projects.append(project)
    return {"projects": projects, "documents": len(state["documents"])}


@app.post("/api/ingestion/projects")
def ingestion_create_project(payload: IngestionProjectInput) -> dict[str, Any]:
    try: return create_project(payload.model_dump())
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@app.delete("/api/ingestion/projects/{project_id}")
def ingestion_delete_project(project_id: str) -> dict[str, str]:
    if not delete_project(project_id):
        raise HTTPException(404, "Project not found")
    return {"status": "deleted", "project_id": project_id}


@app.delete("/api/ingestion/documents/{document_id}")
def ingestion_delete_document(document_id: str) -> dict[str, str]:
    try:
        document = delete_document(document_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not document:
        raise HTTPException(404, "Document not found")
    return {"status": "deleted", "document_id": document_id}


@app.get("/api/ingestion/projects/{project_id}")
def ingestion_project(project_id: str) -> dict[str, Any]:
    project = get_project(project_id)
    if not project: raise HTTPException(404, "Project not found")
    state = read_state(); return {**project, "documents": [public_document(d) for d in state["documents"] if d["project_id"] == project_id]}


@app.post("/api/ingestion/projects/{project_id}/documents")
async def ingestion_upload(project_id: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
    if not get_project(project_id): raise HTTPException(404, "Project not found")
    uploaded = []
    for file in files:
        try: uploaded.append(add_document(project_id, file.filename or "upload.pdf", await file.read()))
        except (ValueError, KeyError) as exc: raise HTTPException(422, str(exc)) from exc
    return {"documents": uploaded}


@app.post("/api/ingestion/projects/{project_id}/curate")
def ingestion_curate_project(project_id: str) -> dict[str, Any]:
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    state = read_state()
    documents = [d for d in state["documents"] if d["project_id"] == project_id and d.get("status") in {"completed", "completed_with_warnings"}]
    if not documents:
        raise HTTPException(422, "No completed PDF is ready for AI curation")
    results = []
    for document in documents:
        folder = document_path(project, document["id"])
        try:
            raw_path = folder / (document.get("raw_companies_artifact") or "company_candidates_raw.json")
            candidates_path = folder / "company_candidates.json"
            if not raw_path.is_file():
                raw_path = candidates_path
            summary = load_and_curate(raw_path, candidates_path)
            curated_candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
            csv_path = folder / "company_candidates.csv"
            fields = list(curated_candidates[0].keys()) if curated_candidates else ["company_name", "legal_entity", "address", "district", "city", "province", "business_sector", "source_url", "evidence", "investment_type", "phone_number"]
            with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(curated_candidates)
            document["companies_artifact"] = "company_candidates.json"
            document["curation_artifact"] = "company_candidates.json"
            document["companies_count"] = summary["accepted"]
            document["curation"] = summary
            results.append({"document_id": document["id"], **summary, "artifact": "company_candidates.json"})
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            detail = str(exc)
            status_code = 429 if "HTTP 429" in detail else 502
            raise HTTPException(status_code, detail) from exc
    write_state(state)
    return {"status": "curated", "documents": results}


@app.get("/api/regions/{province_code}/{region_code}/business-database-mapping")
def region_business_database_mapping(province_code: str, region_code: str) -> dict[str, Any]:
    project = {"province_code": province_code, "regency_code": region_code, "province_name": "", "regency_name": ""}
    try:
        # project_path performs the same administrative validation and name resolution as ingestion.
        province_item, region_item = province(province_code), region(region_code)
        if not province_item or not region_item or region_item.province_id != province_item.id:
            raise HTTPException(404, "Region tidak valid")
        path = region_mapping_path({**project, "province_name": province_item.name, "region_name": region_item.name})
        if not path.is_file():
            raise HTTPException(404, "Business database mapping for this region is not available")
        return validate_mapping_payload(json.loads(path.read_text(encoding="utf-8")))
    except HTTPException:
        raise
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(422, f"Invalid regional business database mapping: {exc}") from exc


@app.post("/api/ingestion/projects/{project_id}/process-osm")
def ingestion_process_osm(project_id: str) -> dict[str, Any]:
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    state = read_state()
    documents = [d for d in state["documents"] if d["project_id"] == project_id and d.get("status") in {"completed", "completed_with_warnings"}]
    if not documents:
        raise HTTPException(422, "No completed PDF candidate data is available for this project")
    candidates: list[dict[str, Any]] = []
    for document in documents:
        path = document_path(project, document["id"]) / (document.get("companies_artifact") or "company_candidates.json")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(422, f"Candidate JSON for {document['id']} is missing or invalid: {exc}") from exc
        if not isinstance(payload, list):
            raise HTTPException(422, f"Candidate JSON for {document['id']} must be an array")
        candidates.extend(item for item in payload if isinstance(item, dict))
    if not candidates:
        raise HTTPException(422, "Candidate data is empty; nothing to process")
    osm_path = Path(__file__).parent / "data" / "businesses.json"
    try:
        osm_records = json.loads(osm_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(422, f"OSM source data is missing or invalid: {exc}") from exc
    if not isinstance(osm_records, list):
        raise HTTPException(422, "OSM source data must be an array")
    try:
        mapping = build_mapping_for_sources(candidates, osm_records, f"project:{project_id}:company_candidates.json", osm_path.name, region_name=project["region_name"])
        output = region_mapping_path(project)
        atomic_json_write(output, mapping)
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(422, f"OSM processing failed: {exc}") from exc
    return {"status": "processed", "project_id": project_id, "region": {"province": project["province_name"], "region": project["region_name"]}, "path": str(output), "summary": mapping["summary"]}


@app.post("/api/ingestion/projects/{project_id}/process")
def ingestion_process_project(project_id: str) -> dict[str, Any]:
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    state = read_state()
    documents = [d for d in state["documents"] if d["project_id"] == project_id and d["status"] in {"uploaded", "failed"}]
    if not documents:
        raise HTTPException(422, "No uploaded PDF is ready to process")
    for document in documents:
        queue_document(document["id"])
    return {"status": "queued", "documents": len(documents)}


@app.post("/api/ingestion/documents/{document_id}/retry")
def ingestion_retry(document_id: str) -> dict[str, Any]:
    document = get_document(document_id)
    if not document: raise HTTPException(404, "Document not found")
    queue_document(document_id); return public_document(get_document(document_id))


@app.get("/api/ingestion/documents/{document_id}")
def ingestion_document(document_id: str) -> dict[str, Any]:
    document = get_document(document_id)
    if not document: raise HTTPException(404, "Document not found")
    return public_document(document)


@app.get("/api/ingestion/delete-route-status")
def ingestion_delete_route_status() -> dict[str, Any]:
    return {"delete_company_route": True, "route": "/api/ingestion/documents/{document_id}/companies/{company_index}"}


@app.get("/api/ingestion/documents/{document_id}/companies")
def ingestion_companies(document_id: str) -> list[dict[str, Any]]:
    document = get_document(document_id); project = get_project(document["project_id"]) if document else None
    if not document or not project or document.get("status") not in {"completed", "completed_with_warnings"}: return []
    path = document_path(project, document_id) / (document.get("companies_artifact") or "company_candidates.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []
    except (OSError, json.JSONDecodeError): return []


@app.put("/api/ingestion/documents/{document_id}/companies/{company_index}")
def ingestion_update_company(document_id: str, company_index: int, payload: dict[str, Any]) -> dict[str, Any]:
    document = get_document(document_id); project = get_project(document["project_id"]) if document else None
    if not document or not project: raise HTTPException(404, "Document not found")
    folder = document_path(project, document_id)
    json_path = folder / (document.get("companies_artifact") or "company_candidates.json")
    csv_path = folder / (document.get("companies_csv_artifact") or "company_candidates.csv")
    try: candidates = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): raise HTTPException(404, "Candidates artifact not found")
    if not isinstance(candidates, list) or company_index < 0 or company_index >= len(candidates): raise HTTPException(404, "Candidate not found")
    allowed = {"company_name", "legal_entity", "address", "district", "city", "province", "business_sector", "source_url", "evidence", "investment_type", "phone_number"}
    candidates[company_index] = {key: str(payload.get(key, "")) if key in allowed else value for key, value in candidates[company_index].items()}
    for key in allowed:
        if key in payload: candidates[company_index][key] = str(payload[key] or "")
    json_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = list(candidates[0].keys()) if candidates else list(allowed)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(candidates)
    return candidates[company_index]


@app.delete("/api/ingestion/documents/{document_id}/companies/{company_index}")
def ingestion_delete_company(document_id: str, company_index: int) -> dict[str, Any]:
    document = get_document(document_id); project = get_project(document["project_id"]) if document else None
    if not document or not project: raise HTTPException(404, "Document not found")
    folder = document_path(project, document_id)
    json_path = folder / (document.get("companies_artifact") or "company_candidates.json")
    csv_path = folder / (document.get("companies_csv_artifact") or "company_candidates.csv")
    try: candidates = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): raise HTTPException(404, "Candidates artifact not found")
    if not isinstance(candidates, list) or company_index < 0 or company_index >= len(candidates): raise HTTPException(404, "Candidate not found")
    candidates.pop(company_index)
    json_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = list(candidates[0].keys()) if candidates else ["company_name", "legal_entity", "address", "district", "city", "province", "business_sector", "source_url", "evidence", "investment_type", "phone_number"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(candidates)
    state = read_state()
    for item in state.get("documents", []):
        if item.get("id") == document_id: item["companies_count"] = len(candidates)
    write_state(state)
    return {"deleted": True, "companies_count": len(candidates)}


@app.get("/api/ingestion/documents/{document_id}/artifact/{artifact}")
def ingestion_artifact(document_id: str, artifact: str) -> Response:
    document = get_document(document_id); project = get_project(document["project_id"]) if document else None
    allowed = {"original": "original.pdf", "json": document.get("json_artifact") if document else None, "markdown": document.get("markdown_artifact") if document else None, "log": document.get("processing_log") if document else None, "companies-raw": document.get("raw_companies_artifact") if document else None, "companies": document.get("companies_artifact") if document else None, "companies-curated": document.get("curation_artifact") if document else None, "companies-csv": document.get("companies_csv_artifact") if document else None}
    if not document or not project or artifact not in allowed or not allowed[artifact]: raise HTTPException(404, "Artifact not found")
    path = document_path(project, document_id) / allowed[artifact]
    if not path.is_file(): raise HTTPException(404, "Artifact not found")
    media = "application/pdf" if artifact == "original" else "application/json" if artifact in {"json", "companies-raw", "companies", "companies-curated"} else "text/csv" if artifact == "companies-csv" else "text/plain"
    return Response(content=path.read_bytes(), media_type=media, headers={"Content-Disposition": f'attachment; filename="{path.name}"'})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "data_file": str(Path(__file__).parent / "data" / "businesses.json")}


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
