"""Persistent local PDF ingestion using the existing OpenDataLoader package."""
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from backend.administrative_reference import validate_pair
from backend.ai_curation import load_and_curate

def validate_administrative_pair(province_code: str, regency_code: str, province_name: str = "", regency_name: str = "") -> tuple[str, str]:
    province, region = validate_pair(province_code, regency_code)
    return province.name, region.name

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = Path(os.getenv("PDF_OUTPUT_ROOT", str(ROOT / "output" / "pdf-parser"))).resolve()
STATE_PATH = ROOT / "backend" / "data" / "pdf_ingestion.json"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
MAX_BYTES = int(os.getenv("PDF_MAX_BYTES", str(100 * 1024 * 1024)))
MAX_DOCUMENTS = int(os.getenv("PDF_MAX_DOCUMENTS", "20"))
TIMEOUT = int(os.getenv("PDF_EXTRACTION_TIMEOUT", "3600"))
LOCK = threading.Lock()
STATE_LOCK_PATH = STATE_PATH.with_suffix(".lock")


@contextmanager
def state_file_lock() -> Iterator[None]:
    """Serialize state writes across threads and separate backend processes."""
    STATE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = STATE_LOCK_PATH.open("a+b")
    try:
        if os.name == "nt":
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)

            import msvcrt
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"projects": [], "documents": []}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def write_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        # The lock must cover both temporary-file creation and replacement,
        # while the temporary file itself must be closed before replace().
        with state_file_lock():
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=STATE_PATH.parent,
                prefix=f"{STATE_PATH.stem}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                json.dump(state, temporary, ensure_ascii=False, indent=2)
                temporary.flush()
                os.fsync(temporary.fileno())

            temporary_path = Path(temporary_name)
            for attempt in range(30):
                try:
                    temporary_path.replace(STATE_PATH)
                    return
                except PermissionError:
                    if attempt == 29:
                        # Some Windows services briefly hold the destination
                        # file without honoring the advisory lock. Preserve
                        # the state update by writing the destination directly.
                        try:
                            STATE_PATH.write_text(
                                temporary_path.read_text(encoding="utf-8"),
                                encoding="utf-8",
                            )
                            return
                        except PermissionError:
                            raise
                    time.sleep(0.2)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def safe_path(path: Path) -> Path:
    resolved = path.resolve()
    if resolved != OUTPUT_ROOT and OUTPUT_ROOT not in resolved.parents:
        raise ValueError("artifact path escapes the configured output root")
    return resolved


def project_path(project: dict[str, Any]) -> Path:
    province_name, regency_name = validate_administrative_pair(project["province_code"], project["regency_code"], project["province_name"], project["regency_name"])
    return safe_path(OUTPUT_ROOT / province_name / regency_name / project["id"])


def document_path(project: dict[str, Any], document_id: str) -> Path:
    return safe_path(project_path(project) / document_id)


def public_document(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    result["artifact_location"] = f"output/pdf-parser/{document['province_name']}/{document['region_name']}/{document['project_id']}/{document['id']}"
    return result


def get_project(project_id: str) -> dict[str, Any] | None:
    return next((item for item in read_state()["projects"] if item["id"] == project_id), None)


def get_document(document_id: str) -> dict[str, Any] | None:
    return next((item for item in read_state()["documents"] if item["id"] == document_id), None)


def delete_document(document_id: str) -> dict[str, Any] | None:
    with LOCK:
        state = read_state()
        document = next((item for item in state["documents"] if item["id"] == document_id), None)
        if not document:
            return None
        if document.get("status") in {"queued", "processing"}:
            raise ValueError("Document is currently being processed")
        project = next((item for item in state["projects"] if item["id"] == document["project_id"]), None)
        state["documents"] = [item for item in state["documents"] if item["id"] != document_id]
        write_state(state)
    if project:
        try:
            import shutil
            folder = document_path(project, document_id)
            if folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
        except (OSError, ValueError):
            pass
    return document


def delete_project(project_id: str) -> bool:
    with LOCK:
        state = read_state()
        project = next((item for item in state["projects"] if item["id"] == project_id), None)
        if not project:
            return False
        state["projects"] = [item for item in state["projects"] if item["id"] != project_id]
        state["documents"] = [item for item in state["documents"] if item["project_id"] != project_id]
        write_state(state)
    # State deletion must not fail just because an old artifact is locked by
    # a running parser or cannot be removed by the current OS account.
    try:
        folder = project_path(project)
        if folder.exists():
            import shutil
            shutil.rmtree(folder, ignore_errors=True)
    except (OSError, ValueError):
        # The project and documents are already removed from persistent state.
        # A later cleanup can remove orphaned artifacts without blocking DELETE.
        pass
    return True


def create_project(payload: dict[str, Any]) -> dict[str, Any]:
    province_name, regency_name = validate_administrative_pair(payload["province_code"], payload["regency_code"], payload["province_name"], payload["regency_name"])
    project = {"id": f"project_{uuid.uuid4().hex}", "province_code": payload["province_code"], "province_name": province_name, "regency_code": payload["regency_code"], "regency_name": regency_name, "region_name": regency_name, "region_type": "kota" if regency_name.lower().startswith("kota ") else "kabupaten", "source_year": payload.get("source_year"), "source_category": payload.get("source_category"), "description": payload.get("description"), "notes": payload.get("notes"), "status": "active", "created_at": now(), "updated_at": now()}
    with LOCK:
        state = read_state(); state["projects"].append(project); write_state(state)
    project_path(project).mkdir(parents=True, exist_ok=True)
    return project


def add_document(project_id: str, filename: str, content: bytes) -> dict[str, Any]:
    project = get_project(project_id)
    if not project: raise KeyError("project not found")
    if len(content) > MAX_BYTES: raise ValueError(f"file exceeds {MAX_BYTES} byte limit")
    if not content.startswith(b"%PDF-"): raise ValueError("uploaded content is not a PDF")
    digest = hashlib.sha256(content).hexdigest()
    with LOCK:
        state = read_state()
        if len([d for d in state["documents"] if d["project_id"] == project_id]) >= MAX_DOCUMENTS: raise ValueError("project document limit reached")
        if any(d["project_id"] == project_id and d["sha256"] == digest for d in state["documents"]): raise ValueError("identical PDF already uploaded to this project")
        document_id = f"document_{uuid.uuid4().hex}"
        folder = document_path(project, document_id); folder.mkdir(parents=True, exist_ok=False)
        (folder / "original.pdf").write_bytes(content)
        document = {"id": document_id, "project_id": project_id, "province_name": project["province_name"], "region_name": project["region_name"], "original_filename": Path(filename).name, "sha256": digest, "status": "uploaded", "uploaded_at": now(), "started_at": None, "completed_at": None, "parser": "opendataloader-pdf 2.5.13", "json_artifact": None, "markdown_artifact": None, "processing_log": None, "warnings": [], "error": None}
        state["documents"].append(document); write_state(state)
    return public_document(document)


def _update(document_id: str, **changes: Any) -> None:
    with LOCK:
        state = read_state(); item = next(d for d in state["documents"] if d["id"] == document_id); item.update(changes); write_state(state)


def extraction_summary(payload: Any) -> dict[str, int]:
    """Return conservative counts without assuming a single parser JSON schema."""
    nodes = payload if isinstance(payload, list) else payload.get("elements", []) if isinstance(payload, dict) else []
    text = " ".join(str(item.get("content", "")) for item in nodes if isinstance(item, dict)) if isinstance(nodes, list) else ""
    companies = sum(1 for item in nodes if isinstance(item, dict) and str(item.get("type", "")).lower() in {"company", "business", "establishment"}) if isinstance(nodes, list) else 0
    if not companies:
        companies = sum(1 for line in text.splitlines() if any(token in line.lower() for token in (" pt ", " cv ", " ud ")))
    return {"companies": companies, "elements": len(nodes) if isinstance(nodes, list) else 0, "characters": len(text)}


def process(document_id: str) -> None:
    document = get_document(document_id); project = get_project(document["project_id"]) if document else None
    if not document or not project: return
    folder = document_path(project, document_id); log_path = folder / "processing.log"
    _update(document_id, status="processing", started_at=now(), error=None)
    try:
        log_path.write_text(f"{now()} — queued → processing\n{now()} — OpenDataLoader started\n", encoding="utf-8")
        command = [str(PYTHON), "-c", "import sys,opendataloader_pdf; opendataloader_pdf.convert(input_path=[sys.argv[1]], output_dir=sys.argv[2], format='json,markdown')", str(folder / "original.pdf"), str(folder)]
        result = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True, timeout=TIMEOUT, shell=False)
        with log_path.open("a", encoding="utf-8") as handle: handle.write(f"{now()} — OpenDataLoader completed (exit {result.returncode})\n")
        json_files = [p for p in folder.glob("*.json") if p.name != "metadata.json"]
        markdown_files = list(folder.glob("*.md"))
        if result.returncode != 0 or not json_files: raise RuntimeError(f"parser exited {result.returncode}; JSON artifact missing")
        parsed = json.loads(json_files[0].read_text(encoding="utf-8"))
        raw_json, companies_json, companies_csv = folder / "company_candidates_raw.json", folder / "company_candidates.json", folder / "company_candidates.csv"
        parser_command = [str(PYTHON), str(ROOT / "backend" / "pdf_tools" / "extract_company_candidates.py"), "--input-json", str(json_files[0]), "--output-json", str(raw_json), "--output-csv", str(companies_csv), "--city", project["region_name"], "--province", project["province_name"]]
        if markdown_files: parser_command += ["--input-markdown", str(markdown_files[0])]
        with log_path.open("a", encoding="utf-8") as handle: handle.write(f"{now()} — Parsing company fields started\n")
        extracted = subprocess.run(parser_command, cwd=str(ROOT), capture_output=True, text=True, timeout=TIMEOUT)
        candidates = json.loads(raw_json.read_text(encoding="utf-8")) if extracted.returncode == 0 else []
        if not isinstance(candidates, list): raise RuntimeError("company candidates artifact must be a flat array")
        companies_json.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        with log_path.open("a", encoding="utf-8") as handle: handle.write(f"{now()} — Extracted {len(candidates)} valid companies; raw and live JSON artifacts generated\n")
        warnings = [x[-2000:] for x in (result.stderr, extracted.stderr) if x]
        _update(document_id, status="completed" if not warnings else "completed_with_warnings", completed_at=now(), json_artifact=json_files[0].name, markdown_artifact=markdown_files[0].name if markdown_files else None, raw_companies_artifact=raw_json.name, companies_artifact=companies_json.name, companies_csv_artifact=companies_csv.name, companies_count=len(candidates), processing_log=log_path.name, extraction=extraction_summary(parsed), warnings=warnings)
    except Exception as exc:
        log_path.write_text(str(exc), encoding="utf-8"); _update(document_id, status="failed", processing_log=log_path.name, error=str(exc))


def queue_document(document_id: str) -> None:
    _update(document_id, status="queued")
    threading.Thread(target=process, args=(document_id,), daemon=True).start()
