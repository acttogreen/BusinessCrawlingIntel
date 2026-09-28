import csv
import io
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.storage import read_activities, read_businesses, read_metadata


app = FastAPI(title="Surakarta Business Intelligence API", version="0.1.0")


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "data_file": str(Path(__file__).parent / "data" / "businesses.json")}


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
