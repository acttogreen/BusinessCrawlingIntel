import os
import stat
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def _parse_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def read_preferences() -> dict[str, Any] | None:
    values = _parse_env()
    provider = values.get("AI_PROVIDER", "openai").strip().lower()
    token = values.get("AI_TOKEN", values.get("OPENAI_API_KEY", "")).strip()
    endpoint = values.get("AI_ENDPOINT", "").strip()
    if provider in {"ollama", "local"} and not endpoint:
        endpoint = "http://127.0.0.1:11434/v1"
    if provider in {"openai", "groq", "together"} and not endpoint:
        endpoint = {"openai": "https://api.openai.com/v1", "groq": "https://api.groq.com/openai/v1", "together": "https://api.together.xyz/v1"}[provider]
    if not token and provider not in {"ollama", "local"}:
        return None
    return {
        "provider": provider,
        "model": values.get("AI_MODEL", "gpt-4o-mini"),
        "token": token,
        "endpoint": endpoint,
        "batch_size": int(values.get("AI_BATCH_SIZE", "5")),
        "confidence": float(values.get("AI_CONFIDENCE", "0.75")),
    }


def write_preferences(settings: dict[str, Any]) -> None:
    existing = _parse_env()
    token = str(settings.get("token", "")).strip()
    if not token:
        token = existing.get("AI_TOKEN", existing.get("OPENAI_API_KEY", "")).strip()
    settings = {**settings, "token": token}
    lines = [
        "# Local AI settings. This file is ignored by Git; do not commit it.",
        f"AI_TOKEN={settings.get('token', '')}",
        f"OPENAI_API_KEY={settings.get('token', '')}",
        f"AI_PROVIDER={settings.get('provider', 'openai')}",
        f"AI_MODEL={settings.get('model', 'gpt-4o-mini')}",
        f"AI_ENDPOINT={settings.get('endpoint', '')}",
        f"AI_BATCH_SIZE={settings.get('batch_size', 5)}",
        f"AI_CONFIDENCE={settings.get('confidence', 0.75)}",
        "",
    ]
    try:
        ENV_PATH.write_text("\n".join(lines), encoding="utf-8")
        ENV_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
        if os.name == "nt":
            subprocess.run(["attrib", "-R", str(ENV_PATH)], check=False, capture_output=True)
    except OSError as exc:
        raise RuntimeError("AI settings could not be saved to .env") from exc


def preferences_status() -> dict[str, Any]:
    values = _parse_env()
    provider = values.get("AI_PROVIDER", "openai").strip().lower()
    configured = bool(values.get("AI_TOKEN", values.get("OPENAI_API_KEY", "")).strip()) or provider in {"ollama", "local"}
    return {"configured": configured, "provider": provider, "endpoint": values.get("AI_ENDPOINT", ""), "path": str(ENV_PATH), "read_only": False}
