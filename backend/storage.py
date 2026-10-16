import json
from pathlib import Path
from typing import Any

from backend.mapping import mapped_businesses


DATA_DIR = Path(__file__).parent / "data"
BUSINESSES_PATH = DATA_DIR / "businesses.json"
ACTIVITIES_PATH = DATA_DIR / "activities.json"
METADATA_PATH = DATA_DIR / "metadata.json"


def _read(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_businesses() -> list[dict[str, Any]]:
    # Business records are served from regional project mappings only.
    # There is no legacy/root mapping fallback.
    return []


def write_businesses(records: list[dict[str, Any]]) -> None:
    _write(BUSINESSES_PATH, records)


def read_activities() -> list[dict[str, Any]]:
    return _read(ACTIVITIES_PATH, [])


def write_activities(records: list[dict[str, Any]]) -> None:
    _write(ACTIVITIES_PATH, records)


def read_metadata() -> dict[str, Any]:
    return _read(METADATA_PATH, {"source": "openstreetmap", "scope": "Kota Surakarta", "object_count": 0})


def write_metadata(metadata: dict[str, Any]) -> None:
    _write(METADATA_PATH, metadata)

