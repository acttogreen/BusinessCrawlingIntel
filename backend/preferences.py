import base64
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parent.parent
PREFERENCES_DIR = ROOT / "preferences"
PREFERENCES_PATH = PREFERENCES_DIR / "ai_settings.enc"


def _cipher() -> Fernet:
    value = os.getenv("SBI_PREFERENCES_KEY")
    if not value:
        raise RuntimeError("SBI_PREFERENCES_KEY is not configured")
    try:
        base64.urlsafe_b64decode(value.encode())
        return Fernet(value.encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError("SBI_PREFERENCES_KEY must be a valid Fernet key") from exc


def read_preferences() -> dict[str, Any] | None:
    if not PREFERENCES_PATH.exists():
        return None
    try:
        payload = _cipher().decrypt(PREFERENCES_PATH.read_bytes())
        return json.loads(payload.decode("utf-8"))
    except (InvalidToken, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Encrypted preferences cannot be read") from exc


def write_preferences(settings: dict[str, Any]) -> None:
    PREFERENCES_DIR.mkdir(parents=True, exist_ok=True)
    if PREFERENCES_PATH.exists() and os.name == "nt":
        subprocess.run(["attrib", "-R", str(PREFERENCES_PATH)], check=True, capture_output=True)
    encrypted = _cipher().encrypt(json.dumps(settings, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    PREFERENCES_PATH.write_bytes(encrypted)
    try:
        PREFERENCES_PATH.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        if os.name == "nt":
            subprocess.run(["attrib", "+R", str(PREFERENCES_PATH)], check=True, capture_output=True)
    except OSError as exc:
        raise RuntimeError("Preferences were saved but could not be made read-only") from exc


def preferences_status() -> dict[str, Any]:
    return {"configured": PREFERENCES_PATH.exists(), "path": str(PREFERENCES_PATH), "read_only": PREFERENCES_PATH.exists()}
