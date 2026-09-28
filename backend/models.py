from typing import Any


def empty_business() -> dict[str, Any]:
    return {
        "id": "",
        "name": "",
        "category": "unknown",
        "subcategory": "unknown",
        "location": {"latitude": None, "longitude": None},
        "address": {},
        "contact": {},
        "source": "openstreetmap",
        "legal": {"status": "unknown"},
        "investment": {"status": "unknown"},
        "activity": {},
        "metadata": {},
    }
