import os
import stat
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
RULESET_PATH = ROOT / "configuration" / "ruleset.md"
DEFAULT_RULESET = """# Aturan Kurasi dan Verifikasi

## Prinsip umum
- Gunakan bukti dokumen sebagai acuan utama; jangan mengubah evidence.
- Pertahankan setiap kandidat tepat satu kali. Jangan menghapus, menolak, atau menggabungkan kandidat.
- Jangan membuat nilai yang tidak didukung sumber. Jika ragu, pertahankan nilai yang ada dan tandai untuk ditinjau.

## Validasi field
- **Sektor usaha:** gunakan deskripsi kegiatan yang eksplisit; jangan menebak dari nama perusahaan.
- **Kecamatan dan kota/kabupaten:** cocokkan dengan evidence dan konteks sumber. Tandai konflik untuk ditinjau.
- **Nomor telepon:** pertahankan format sumber; verifikasi hanya dengan sumber yang dapat diatribusikan.
- Sertakan alasan untuk setiap perubahan. Untuk sumber internet, sertakan URL.
- Jika bukti tidak cukup, pertahankan nilai yang tersedia dan tandai untuk ditinjau.
"""


def read_ruleset() -> str:
    try:
        if not RULESET_PATH.exists():
            write_ruleset(DEFAULT_RULESET)
        return RULESET_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError("Ruleset could not be read") from exc


def write_ruleset(content: str) -> None:
    try:
        RULESET_PATH.parent.mkdir(parents=True, exist_ok=True)
        RULESET_PATH.write_text(content.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8")
    except OSError as exc:
        raise RuntimeError("Ruleset could not be saved") from exc


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
    provider = values.get("AI_PROVIDER", values.get("OPENAI_API_TYPE", "custom")).strip().lower()
    token = values.get("AI_API_TOKEN", values.get("AI_TOKEN", values.get("OPENAI_API_KEY", ""))).strip()
    endpoint = values.get("AI_ENDPOINT", values.get("OPENAI_API_BASE", "")).strip()
    if provider in {"ollama", "local"} and not endpoint:
        endpoint = "http://127.0.0.1:11434/v1"
    if provider in {"openai", "groq", "together"} and not endpoint:
        endpoint = {"openai": "https://api.openai.com/v1", "groq": "https://api.groq.com/openai/v1", "together": "https://api.together.xyz/v1"}[provider]
    return {
        "provider": provider,
        "model": values.get("AI_MODEL", values.get("OPENAI_MODEL", "")).strip(),
        "token": token,
        "endpoint": endpoint,
        "batch_size": max(1, min(200, int(values.get("AI_BATCH_SIZE", "5")))),
        "timeout_seconds": max(30, min(600, int(values.get("AI_TIMEOUT_SECONDS", "180")))),
        "retry_count": max(0, min(5, int(values.get("AI_RETRY_COUNT", "2")))),
        "concurrency": max(1, min(8, int(values.get("AI_CONCURRENCY", "3")))),
        "confidence": float(values.get("AI_CONFIDENCE", "0.75")),
        "ruleset": read_ruleset(),
        "web_lookup": values.get("AI_WEB_LOOKUP", "false").lower() == "true",
    }


def write_preferences(settings: dict[str, Any]) -> None:
    existing = _parse_env()
    token = str(settings.get("token", "")).strip()
    if not token:
        token = existing.get("AI_API_TOKEN", existing.get("AI_TOKEN", existing.get("OPENAI_API_KEY", ""))).strip()
    settings = {**settings, "token": token}
    lines = [
        "# Local AI settings. This file is ignored by Git; do not commit it.",
        f"AI_TOKEN={settings.get('token', '')}",
        f"AI_API_TOKEN={settings.get('token', '')}",
        f"OPENAI_API_KEY={settings.get('token', '')}",
        f"AI_PROVIDER={settings.get('provider', 'openai')}",
        f"AI_MODEL={settings.get('model', 'gpt-4o-mini')}",
        f"AI_ENDPOINT={settings.get('endpoint', '')}",
        f"AI_BATCH_SIZE={settings.get('batch_size', 5)}",
        f"AI_TIMEOUT_SECONDS={settings.get('timeout_seconds', 180)}",
        f"AI_RETRY_COUNT={settings.get('retry_count', 2)}",
        f"AI_CONCURRENCY={settings.get('concurrency', 3)}",
        f"AI_CONFIDENCE={settings.get('confidence', 0.75)}",
        f"AI_WEB_LOOKUP={'true' if settings.get('web_lookup', False) else 'false'}",
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
    provider = values.get("AI_PROVIDER", values.get("OPENAI_API_TYPE", "custom")).strip().lower()
    configured = bool(values.get("AI_API_TOKEN", values.get("AI_TOKEN", values.get("OPENAI_API_KEY", ""))).strip()) or provider in {"ollama", "local"}
    return {"configured": configured, "provider": provider, "endpoint": values.get("AI_ENDPOINT", ""), "path": str(ENV_PATH), "read_only": False}
