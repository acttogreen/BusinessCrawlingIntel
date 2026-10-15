"""AI preflight and structured company-candidate curation."""
import json
import os
import time
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
        text = "\\n".join(lines).strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        # Some compatible servers append a short explanation after valid JSON.
        decoder = json.JSONDecoder()
        try:
            result, end = decoder.raw_decode(text)
            if text[end:].strip():
                raise exc
        except (json.JSONDecodeError, TypeError) as parse_exc:
            preview = text[max(0, exc.pos - 80):exc.pos + 80].replace("\\n", " ")
            raise RuntimeError(
                f"Provider AI mengembalikan JSON tidak valid pada karakter {exc.pos}: {preview!r}"
            ) from parse_exc
    if not isinstance(result, dict):
        raise RuntimeError("Provider AI mengembalikan JSON dengan bentuk yang tidak didukung.")
    return result


def _json_response(settings: dict[str, Any], prompt: str) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if settings.get("token", "").strip():
        headers["Authorization"] = f"Bearer {settings['token'].strip()}"
    payload = {
        "model": settings.get("model") or "",
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "You are a careful data-quality reviewer. Never invent values. Return only valid JSON."},
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
            if attempt == retry_count:
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


def curate_candidates(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    settings = _settings()
    batch_size = max(1, min(200, int(settings.get("batch_size", 5))))
    minimum = float(settings.get("confidence", 0.75))
    curated: list[dict[str, Any]] = []
    rejected = 0
    field_issues = 0
    batch_timings: list[dict[str, Any]] = []
    started_at = time.perf_counter()
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start:start + batch_size]
        batch_started_at = time.perf_counter()
        prompt = json.dumps({
            "task": "Enrich and reconcile these company candidates. Treat evidence as the primary raw reference, then raw_data.source_text and raw_data.context_lines. Verify district, business_sector, and phone_number against evidence. Internet lookup is allowed only when enabled in settings; cite the URL and keep the raw evidence unchanged. Never replace evidence with web data, invent, or make unsupported inferences. Keep real business entities and remove duplicates/non-business entries.",
            "ruleset": settings.get("ruleset", "Use conservative reconciliation: evidence wins; if conflict or uncertainty remains, preserve the original and mark review."),
            "web_lookup_enabled": bool(settings.get("web_lookup", False)),
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
        batch_timings.append({"batch": start // batch_size + 1, "input": len(batch), "duration_seconds": round(time.perf_counter() - batch_started_at, 2)})
    return curated, {"input": len(candidates), "accepted": len(curated), "rejected": rejected, "field_issues": field_issues, "model": settings.get("model", "gpt-4o-mini"), "duration_seconds": round(time.perf_counter() - started_at, 2), "batch_timings": batch_timings}


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