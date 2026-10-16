"""Background AI-curation jobs with durable status and cache metadata."""
import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.ai_curation import CURATION_VERSION, load_and_curate
from backend.pdf_ingestion import document_path, read_state, write_state
from backend.preferences import read_preferences

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _curation_fingerprint() -> str:
    settings = read_preferences() or {}
    configuration = {
        key: settings.get(key)
        for key in ("provider", "model", "endpoint", "batch_size", "confidence", "ruleset", "web_lookup")
    }
    configuration["curation_version"] = CURATION_VERSION
    encoded = json.dumps(configuration, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        value = _JOBS.get(job_id)
        return dict(value) if value else None


def _run(job_id: str, project_id: str) -> None:
    try:
        state = read_state()
        documents = [d for d in state["documents"] if d["project_id"] == project_id and d.get("status") in {"completed", "completed_with_warnings"}]
        job = get_job(job_id) or {}
        job["total_documents"] = len(documents)
        for index, document in enumerate(documents):
            folder = document_path(next(p for p in state["projects"] if p["id"] == project_id), document["id"])
            raw = folder / (document.get("raw_companies_artifact") or "company_candidates_raw.json")
            target = folder / "company_candidates.json"
            if not raw.is_file(): raw = target
            cache_dir = folder / "curation_cache"
            manifest = cache_dir / "manifest.json"
            fingerprint = _fingerprint(raw)
            curation_fingerprint = _curation_fingerprint()
            cached = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
            if (
                cached.get("source_hash") == fingerprint
                and cached.get("curation_fingerprint") == curation_fingerprint
                and target.is_file()
                and cached.get("status") == "completed"
            ):
                summary = cached.get("summary", {})
            else:
                summary = load_and_curate(raw, target)
                _atomic(manifest, {
                    "source_hash": fingerprint,
                    "curation_fingerprint": curation_fingerprint,
                    "status": "completed",
                    "summary": summary,
                    "updated_at": _now(),
                })
            document["companies_artifact"] = "company_candidates.json"
            document["curation_artifact"] = "company_candidates.json"
            document["companies_count"] = summary.get("accepted", 0)
            document["curation"] = summary
            job.update({"completed_documents": index + 1, "current_document": document["id"], "progress": round((index + 1) / max(1, len(documents)), 3)})
            with _LOCK: _JOBS[job_id] = dict(job)
            write_state(state)
        job.update({"status": "completed", "progress": 1, "finished_at": _now()})
        write_state(state)
    except Exception as exc:
        job.update({"status": "failed", "error": str(exc), "finished_at": _now()})
    with _LOCK: _JOBS[job_id] = dict(job)


def start_job(project_id: str) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    job = {"job_id": job_id, "project_id": project_id, "status": "running", "progress": 0, "completed_documents": 0, "started_at": _now()}
    with _LOCK: _JOBS[job_id] = job
    threading.Thread(target=_run, args=(job_id, project_id), daemon=True).start()
    return job


__all__ = ["get_job", "start_job"]
