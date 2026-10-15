import csv
import io
import json
import zipfile
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
from backend.preferences import preferences_status, write_preferences


app = FastAPI(title="Surakarta Business Intelligence API", version="0.1.0")


class PreferencesInput(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=100)
    token: str = Field(min_length=1, max_length=1000)
    batch_size: int = Field(ge=1, le=200)
    confidence: float = Field(ge=0, le=1)
    mapping: dict[str, Any]


class TokenCheckInput(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    token: str = Field(min_length=1, max_length=1000)


@app.get("/api/preferences/status")
def preference_status() -> dict[str, Any]:
    return preferences_status()


@app.post("/api/preferences/check-token")
def check_preference_token(payload: TokenCheckInput) -> dict[str, Any]:
    provider = payload.provider.lower().strip()
    base_urls = {"openai": "https://api.openai.com", "anthropic": "https://api.anthropic.com", "custom": "https://api.openai.com"}
    base_url = base_urls.get(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    headers = {"Authorization": f"Bearer {payload.token.strip()}"}
    if provider == "anthropic":
        headers = {"x-api-key": payload.token.strip(), "anthropic-version": "2023-06-01"}
    try:
        response = requests.get(f"{base_url}/v1/models", headers=headers, timeout=15)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Provider tidak dapat dihubungi") from exc
    if response.ok:
        return {"connected": True, "provider": provider, "message": "Token valid dan provider dapat dihubungi"}
    if response.status_code in {401, 403}:
        return {"connected": False, "provider": provider, "message": "Token ditolak oleh provider"}
    return {"connected": False, "provider": provider, "message": f"Provider merespons HTTP {response.status_code}"}


@app.post("/api/preferences")
def save_preferences(payload: PreferencesInput) -> dict[str, Any]:
    try:
        write_preferences(payload.model_dump())
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"saved": True, **preferences_status()}


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
    allowed = {"original": "original.pdf", "json": document.get("json_artifact") if document else None, "markdown": document.get("markdown_artifact") if document else None, "log": document.get("processing_log") if document else None, "companies": document.get("companies_artifact") if document else None, "companies-csv": document.get("companies_csv_artifact") if document else None}
    if not document or not project or artifact not in allowed or not allowed[artifact]: raise HTTPException(404, "Artifact not found")
    path = document_path(project, document_id) / allowed[artifact]
    if not path.is_file(): raise HTTPException(404, "Artifact not found")
    media = "application/pdf" if artifact == "original" else "application/json" if artifact in {"json", "companies"} else "text/csv" if artifact == "companies-csv" else "text/plain"
    return Response(content=path.read_bytes(), media_type=media, headers={"Content-Disposition": f'attachment; filename="{path.name}"'})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "data_file": str(Path(__file__).parent / "data" / "businesses.json")}


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
