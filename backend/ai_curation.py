"""AI preflight and structured company-candidate curation."""
import json
import os
from pathlib import Path
from typing import Any

import requests

from backend.preferences import read_preferences

FIELDS = [
    "company_name", "legal_entity", "address", "district", "city", "province",
    "business_sector", "source_url", "evidence", "investment_type", "phone_number",
]


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
    if response.status_code in {401, 403}:
        raise RuntimeError("Token OpenAI ditolak oleh provider.")
    if not response.ok:
        raise RuntimeError(f"OpenAI merespons HTTP {response.status_code}.")
    return {"connected": True, "provider": settings.get("provider", "openai"), "model": settings.get("model", "gpt-4o-mini")}


def _json_response(settings: dict[str, Any], prompt: str) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if settings.get("token", "").strip():
        headers["Authorization"] = f"Bearer {settings['token'].strip()}"
    payload = {
        "model": settings.get("model") or "gpt-4o-mini",
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "You are a careful data-quality reviewer. Never invent values. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
    }
    url = f"{_base_endpoint(settings)}/chat/completions"
    last_error: requests.RequestException | None = None
    for attempt in range(2):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=(15, 600))
            break
        except requests.Timeout as exc:
            last_error = exc
            if attempt == 1:
                raise RuntimeError("AI curation timed out after 600 seconds. Kurangi AI_BATCH_SIZE jika model lokal masih lambat.") from exc
        except requests.ConnectionError as exc:
            last_error = exc
            if attempt == 1:
                raise RuntimeError("Provider AI terputus saat kurasi setelah percobaan ulang.") from exc
    else:
        raise RuntimeError("Provider AI tidak dapat dihubungi.") from last_error
    if not response.ok:
        detail = response.text.strip().replace("\n", " ")[:300]
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"OpenAI curation failed with HTTP {response.status_code}{suffix}.")
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def curate_candidates(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    settings = _settings()
    batch_size = max(1, min(200, int(settings.get("batch_size", 5))))
    minimum = float(settings.get("confidence", 0.75))
    curated: list[dict[str, Any]] = []
    rejected = 0
    field_issues = 0
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start:start + batch_size]
        prompt = json.dumps({
            "task": "Enrich and reconcile these company candidates. Use only raw_data.source_text, raw_data.context_lines, and evidence as source evidence. You may fill or correct a field only when the source explicitly supports it; otherwise preserve the original value or leave it empty. Never infer, browse, or guess. Keep real business entities and remove duplicates/non-business entries.",
            "required_fields": FIELDS,
            "minimum_confidence": minimum,
            "candidates": batch,
            "output": {"candidates": "array", "rejected": "integer", "field_issues": "integer"},
            "candidate_shape": {"candidate": "original fields plus preserved raw_data and extracted_data", "field_validation": {"field": "string", "valid": "boolean", "confidence": "number", "reason": "string", "source": "evidence|raw_data|missing"}, "curation_status": "accepted|review"},
        }, ensure_ascii=False)
        result = _json_response(settings, prompt)
        for item in result.get("candidates", []):
            if not isinstance(item, dict):
                continue
            validations = item.get("field_validation", {})
            item["field_validation"] = validations if isinstance(validations, dict) else {}
            item["curation_status"] = item.get("curation_status", "review")
            # These provenance fields are controlled by the extractor, not the model.
            source_name = str(item.get("company_name", "")).casefold()
            original = next((candidate for candidate in batch if str(candidate.get("company_name", "")).casefold() == source_name), {})
            item["raw_data"] = original.get("raw_data", {})
            item["extracted_data"] = original.get("extracted_data", {})
            curated.append(item)
        rejected += int(result.get("rejected", 0) or 0)
        field_issues += int(result.get("field_issues", 0) or 0)
    return curated, {"input": len(candidates), "accepted": len(curated), "rejected": rejected, "field_issues": field_issues, "model": settings.get("model", "gpt-4o-mini")}


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
    curated, summary = curate_candidates(input_candidates)
    temporary_path = target_path.with_name(f".{target_path.name}.tmp")
    try:
        temporary_path.write_text(json.dumps(curated, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary_path, target_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    summary["validation"] = validate_fields(curated)
    summary["batches"] = (len(input_candidates) + max(1, min(200, int(_settings().get("batch_size", 5)))) - 1) // max(1, min(200, int(_settings().get("batch_size", 5)))) if input_candidates else 0
    return summary


__all__ = ["check_saved_connection", "curation_status", "load_and_curate", "preference_error"]