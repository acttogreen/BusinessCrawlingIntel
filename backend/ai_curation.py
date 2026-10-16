"""AI preflight and structured company-candidate curation."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import requests

from backend.preferences import read_preferences

FIELDS = [
    "company_name", "legal_entity", "address", "district", "city", "province",
    "business_sector", "source_url", "evidence", "investment_type", "phone_number",
]
MAX_CANDIDATE_EVIDENCE_CHARS = 1600
MAX_BATCH_CANDIDATE_CHARS = 12000
CURATION_VERSION = 2


def _base_endpoint(settings: dict[str, Any]) -> str:
    """Return the provider's OpenAI-compatible base URL without an operation path."""
    endpoint = str(settings.get("endpoint", "")).strip().rstrip("/")
    for suffix in ("/chat/completions", "/models"):
        if endpoint.lower().endswith(suffix):
            endpoint = endpoint[:-len(suffix)].rstrip("/")
    return endpoint


def _settings() -> dict[str, Any]:
    settings = read_preferences()
    if not settings:
        raise RuntimeError("AI belum dikonfigurasi. Simpan pengaturan provider terlebih dahulu.")
    provider = str(settings.get("provider", "openai")).lower()
    if provider not in {"openai", "groq", "together", "ollama", "local", "custom"}:
        raise RuntimeError(f"Provider AI tidak didukung: {provider}")
    if provider not in {"ollama", "local"} and not str(settings.get("token", "")).strip():
        raise RuntimeError("Token AI belum dikonfigurasi. Simpan token di Settings terlebih dahulu.")
    if not str(settings.get("endpoint", "")).strip():
        raise RuntimeError("Endpoint AI belum dikonfigurasi.")
    return settings


def check_saved_connection() -> dict[str, Any]:
    settings = _settings()
    headers = {"Authorization": f"Bearer {settings['token'].strip()}"} if settings.get("token", "").strip() else {}
    response = requests.get(f"{_base_endpoint(settings)}/models", headers=headers, timeout=15)
    provider = str(settings.get("provider", "custom"))
    if response.status_code in {401, 403}:
        raise RuntimeError(f"Token/provider {provider} ditolak.")
    if not response.ok:
        raise RuntimeError(f"Provider {provider} merespons HTTP {response.status_code}.")
    return {"connected": True, "provider": provider, "model": settings.get("model", "")}


def _parse_json_content(content: Any) -> dict[str, Any]:
    """Parse a provider response while tolerating common formatting wrappers."""
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Provider AI mengembalikan respons JSON kosong.")
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        # Some compatible servers append a short explanation after valid JSON.
        # Accept that only when the first JSON value is complete; never silently
        # accept a truncated object because that would publish incomplete data.
        decoder = json.JSONDecoder()
        try:
            result, end = decoder.raw_decode(text)
        except (json.JSONDecodeError, TypeError) as parse_exc:
            preview = text[max(0, exc.pos - 80):exc.pos + 80].replace("\n", " ")
            suffix = " Respons kemungkinan terpotong." if not text.rstrip().endswith(("}", "]")) else ""
            raise RuntimeError(
                f"Provider AI mengembalikan JSON tidak valid pada karakter {exc.pos}: {preview!r}.{suffix}"
            ) from parse_exc
        if text[end:].strip():
            preview = text[max(0, exc.pos - 80):exc.pos + 80].replace("\n", " ")
            raise RuntimeError(
                f"Provider AI mengembalikan JSON dengan teks tambahan pada karakter {end}: {preview!r}"
            ) from exc
    if not isinstance(result, dict):
        raise RuntimeError("Provider AI mengembalikan JSON dengan bentuk yang tidak didukung.")
    return result


def _json_response(settings: dict[str, Any], prompt: str, retry_timeouts: bool = True) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if settings.get("token", "").strip():
        headers["Authorization"] = f"Bearer {settings['token'].strip()}"
    payload = {
        "model": settings.get("model") or "",
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "You are a field-level data-quality reviewer, not a candidate filter. Never delete, reject, omit, merge, or deduplicate candidates. Preserve every input candidate exactly once and never invent values. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
    }
    url = f"{_base_endpoint(settings)}/chat/completions"
    last_error: requests.RequestException | None = None
    timeout_seconds = max(30, min(600, int(settings.get("timeout_seconds", 180))))
    retry_count = max(0, min(5, int(settings.get("retry_count", 2))))
    for attempt in range(retry_count + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=(15, timeout_seconds))
            break
        except requests.Timeout as exc:
            last_error = exc
            if attempt == retry_count or not retry_timeouts:
                raise RuntimeError(f"AI curation timed out after {timeout_seconds} seconds. Kurangi ukuran batch jika perlu.") from exc
        except requests.ConnectionError as exc:
            last_error = exc
            if attempt == retry_count:
                raise RuntimeError("Provider AI terputus setelah percobaan ulang.") from exc
    else:
        raise RuntimeError("Provider AI tidak dapat dihubungi.") from last_error
    if not response.ok:
        detail = response.text.strip().replace("\n", " ")[:300]
        suffix = f": {detail}" if detail else ""
        provider = settings.get("provider", "custom")
        raise RuntimeError(f"{provider} curation failed with HTTP {response.status_code}{suffix}.")
    try:
        response_payload = response.json()
        choice = response_payload["choices"][0]
        message = choice["message"]
        content = message.get("content")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Provider AI mengembalikan format respons yang tidak lengkap.") from exc
    if choice.get("finish_reason") == "length":
        raise RuntimeError("Respons AI terpotong karena batas token. Kurangi ukuran batch.")
    return _parse_json_content(content)


def _candidate_prompt_data(candidate: dict[str, Any]) -> dict[str, Any]:
    data = {field: str(candidate.get(field, "") or "") for field in FIELDS}
    evidence = data["evidence"]
    if len(evidence) > MAX_CANDIDATE_EVIDENCE_CHARS:
        company_name = data["company_name"].strip()
        match_at = evidence.casefold().find(company_name.casefold()) if company_name else -1
        start = max(0, match_at - 240) if match_at >= 0 else 0
        excerpt = evidence[start:start + MAX_CANDIDATE_EVIDENCE_CHARS]
        data["evidence"] = ("…" if start else "") + excerpt
        if start + len(excerpt) < len(evidence):
            data["evidence"] += "…"
    data["candidate_id"] = str(candidate.get("candidate_id", ""))
    data["source_index"] = candidate.get("source_index")
    return data


def _candidate_batches(
    candidates: list[dict[str, Any]], batch_size: int
) -> list[tuple[int, list[dict[str, Any]]]]:
    batches: list[tuple[int, list[dict[str, Any]]]] = []
    current: list[dict[str, Any]] = []
    current_size = 2
    start = 0
    for index, candidate in enumerate(candidates):
        compact = _candidate_prompt_data(candidate)
        candidate_size = len(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
        added_size = candidate_size + (1 if current else 0)
        if current and (len(current) >= batch_size or current_size + added_size > MAX_BATCH_CANDIDATE_CHARS):
            batches.append((start, current))
            current = []
            current_size = 2
            start = index
            added_size = candidate_size
        current.append(candidate)
        current_size += added_size
    if current:
        batches.append((start, current))
    return batches


def _normalize_field_validation(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for field in FIELDS:
        validation = value.get(field)
        if not isinstance(validation, dict):
            continue
        try:
            confidence = max(0.0, min(1.0, float(validation.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0.0
        source = validation.get("source")
        normalized[field] = {
            "valid": validation.get("valid") is True,
            "confidence": confidence,
            "reason": str(validation.get("reason", "")),
            "source": source if source in {"evidence", "missing"} else "missing",
        }
    return normalized


def curate_candidates(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    settings = _settings()
    batch_size = max(1, min(200, int(settings.get("batch_size", 5))))
    concurrency = max(1, min(8, int(settings.get("concurrency", 3))))
    minimum = float(settings.get("confidence", 0.75))
    started_at = time.perf_counter()
    batches = _candidate_batches(candidates, batch_size)

    def process_batch(batch_info: tuple[int, list[dict[str, Any]]]) -> tuple[int, list[dict[str, Any]], int, int, dict[str, Any]]:
        start, batch = batch_info
        batch_started_at = time.perf_counter()
        prompt_candidates = [_candidate_prompt_data(candidate) for candidate in batch]
        prompt = json.dumps({
            "task": "Review and curate every input candidate exactly once; this is field-level data quality assistance, NOT candidate selection. NEVER delete, omit, reject, merge, or deduplicate a candidate. Preserve every candidate_id and source_index. Clean OCR artifacts, numbering, table labels, unused words, spacing, capitalization, and punctuation. Verify and revise each of company_name, address, business_sector, phone_number, district (kecamatan), city (kabupaten/kota), and investment_type against candidate.evidence first, then raw_data.source_text/context_lines and extracted_data. Keep all candidates even when evidence or fields are incomplete; preserve the available original value and mark the affected field for review with a reason instead of blanking it. Do not infer unsupported values. Preserve evidence and raw_data/extracted_data unchanged. Match results only by candidate_id, never company_name. Internet lookup is allowed only when enabled; cite URLs in field validation and never replace document evidence with web data. Every input candidate must have exactly one output.",
            "ruleset": str(settings.get("ruleset", "")),
            "web_lookup_enabled": bool(settings.get("web_lookup", False)),
            "required_fields": ["company_name", "address", "business_sector", "phone_number", "district", "city", "investment_type"],
            "minimum_confidence": minimum,
            "candidates": prompt_candidates,
            "input_policy": "Only the fields shown in candidates are available; use evidence and existing field values only.",
            "output": {"candidates": "array containing exactly one flat object with every field in candidate_shape for each input candidate_id; never omit/reject", "rejected": 0, "field_issues": "integer"},
            "candidate_shape": {"candidate_id": "required stable identifier copied exactly", "source_index": "required original line index", "fields": FIELDS, "field_validation": "object keyed by field name", "curation_status": "accepted|review; rejected is forbidden"},
            "rejection_policy": "forbidden; preserve every input candidate",
        }, ensure_ascii=False)
        try:
            result = _json_response(settings, prompt, retry_timeouts=len(batch) == 1)
        except RuntimeError as exc:
            split_required = (
                "AI curation timed out after" in str(exc)
                or "Respons AI terpotong karena batas token" in str(exc)
            )
            if not split_required or len(batch) < 2:
                raise
            midpoint = len(batch) // 2
            left = process_batch((start, batch[:midpoint]))
            right = process_batch((start + midpoint, batch[midpoint:]))
            return start, left[1] + right[1], left[2] + right[2], left[3] + right[3], {
                "batch": sum(1 for batch_start, _ in batches if batch_start <= start),
                "input": len(batch),
                "returned": left[4]["returned"] + right[4]["returned"],
                "fallback": left[4]["fallback"] + right[4]["fallback"],
                "prompt_characters": left[4]["prompt_characters"] + right[4]["prompt_characters"],
                "duration_seconds": round(time.perf_counter() - batch_started_at, 2),
                "split_after_capacity_error": True,
            }
        response_candidates = result.get("candidates")
        if not isinstance(response_candidates, list):
            raise RuntimeError("Provider AI harus mengembalikan array candidates dalam JSON.")
        candidate_ids = {str(candidate.get("candidate_id")) for candidate in batch}
        returned = {}
        for response_item in response_candidates:
            if not isinstance(response_item, dict):
                continue
            response_id = str(response_item.get("candidate_id", ""))
            if response_id in candidate_ids:
                returned[response_id] = response_item
        curated_batch: list[dict[str, Any]] = []
        for candidate in batch:
            candidate_id = str(candidate.get("candidate_id"))
            item = returned.get(candidate_id)
            if isinstance(item, dict) and isinstance(item.get("candidate"), dict):
                item = {**item["candidate"], **item}
            if item is None:
                item = {key: candidate.get(key, "") for key in FIELDS}
                item["candidate_id"] = candidate_id
                item["source_index"] = candidate.get("source_index")
                item["curation_status"] = "review"
                item["field_validation"] = {
                    field: {"valid": False, "confidence": 0, "reason": "AI tidak mengembalikan kandidat; nilai sumber dipertahankan.", "source": "missing"}
                    for field in FIELDS
                }
            validations = item.get("field_validation", {})
            item["field_validation"] = validations if isinstance(validations, dict) else {}
            # Candidate curation is field-level only: enforce retention even if a
            # provider ignores the prompt and labels a record as rejected.
            if item.get("curation_status") not in {"accepted", "review"}:
                item["curation_status"] = "review"
                item.setdefault("field_validation", {})["company_name"] = {
                    "valid": False,
                    "confidence": 0,
                    "reason": "Status rejected dari AI diubah menjadi review; kandidat tetap dipertahankan.",
                    "source": "missing",
                }
            item["candidate_id"] = candidate_id
            item["source_index"] = candidate.get("source_index", item.get("source_index"))
            item["raw_data"] = candidate.get("raw_data", {})
            item["extracted_data"] = candidate.get("extracted_data", {})
            curated_batch.append({
                **{
                    field: str(candidate.get("evidence", "") or "") if field == "evidence"
                    else str(item.get(field, candidate.get(field, "")) or "")
                    for field in FIELDS
                },
                "candidate_id": candidate_id,
                "source_index": candidate.get("source_index"),
                "curation_status": item["curation_status"],
                "field_validation": _normalize_field_validation(item["field_validation"]),
            })
        missing_count = len(batch) - len(returned)
        timing = {
            "batch": sum(1 for batch_start, _ in batches if batch_start <= start),
            "input": len(batch),
            "returned": len(batch) - missing_count,
            "fallback": missing_count,
            "prompt_characters": len(prompt),
            "duration_seconds": round(time.perf_counter() - batch_started_at, 2),
        }
        return start, curated_batch, int(result.get("rejected", 0) or 0), int(result.get("field_issues", 0) or 0), timing

    results = []
    with ThreadPoolExecutor(max_workers=min(concurrency, max(1, len(batches)))) as executor:
        for result in executor.map(process_batch, batches):
            results.append(result)
    results.sort(key=lambda result: result[0])
    curated = [item for _, batch_result, _, _, _ in results for item in batch_result]
    rejected = sum(result[2] for result in results)
    field_issues = sum(result[3] for result in results)
    batch_timings = [result[4] for result in results]
    return curated, {
        "input": len(candidates),
        "accepted": len(curated),
        "rejected": rejected,
        "field_issues": field_issues,
        "model": settings.get("model", "gpt-4o-mini"),
        "curation_version": CURATION_VERSION,
        "duration_seconds": round(time.perf_counter() - started_at, 2),
        "batches": len(batches),
        "batch_timings": batch_timings,
        "concurrency": min(concurrency, max(1, len(batches))),
    }


def curation_status() -> dict[str, Any]:
    status = check_saved_connection()
    return {**status, "configured": True}


def preference_error() -> str:
    try:
        _settings()
        return ""
    except RuntimeError as exc:
        return str(exc)
    except requests.RequestException:
        return "Provider OpenAI tidak dapat dihubungi."
    except Exception:
        return "Token OpenAI tidak dapat diverifikasi."


def validate_fields(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    issues = []
    for index, candidate in enumerate(candidates):
        for field in FIELDS:
            if not str(candidate.get(field, "") or "").strip():
                issues.append({"index": index, "field": field, "valid": False, "reason": "Field kosong"})
    return {"valid": not issues, "issues": issues, "checked": len(candidates) * len(FIELDS)}


def load_and_curate(path: Any, output_path: Any | None = None) -> dict[str, Any]:
    """Curate candidates in batches and atomically publish the combined result.

    The source remains untouched until every AI batch succeeds. This allows the
    caller to use the original company_candidates.json as the live table while
    avoiding a partially curated file when one request fails.
    """
    source_path = Path(path)
    target_path = Path(output_path) if output_path is not None else source_path
    candidates = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(candidates, list):
        raise RuntimeError("company candidates artifact must be a flat array")
    input_candidates = [item for item in candidates if isinstance(item, dict)]
    for index, candidate in enumerate(input_candidates):
        candidate.setdefault("source_index", candidate.get("raw_data", {}).get("source_index", index))
        candidate.setdefault("candidate_id", f"source-{candidate['source_index']}")
        raw_data = candidate.setdefault("raw_data", {})
        raw_data.setdefault("candidate_id", candidate["candidate_id"])
        raw_data.setdefault("source_index", candidate["source_index"])
    curated, summary = curate_candidates(input_candidates)
    temporary_path = target_path.with_name(f".{target_path.name}.tmp")
    try:
        temporary_path.write_text(json.dumps(curated, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary_path, target_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    summary["validation"] = validate_fields(curated)
    return summary


__all__ = ["check_saved_connection", "curation_status", "load_and_curate", "preference_error"]