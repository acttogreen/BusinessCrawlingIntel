import os
import time
from typing import Any

import requests


DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"
USER_AGENT = "SurakartaBusinessIntelligence/0.1 (local research prototype)"


DEFAULT_TAGS = ["shop", "amenity", "office", "craft", "tourism=hotel|guest_house|hostel", "leisure=fitness_centre|sports_centre"]


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_query(area_name: str = "Surakarta", tags: list[str] | None = None, timeout_seconds: int = 60) -> str:
    clauses = []
    for expression in tags or DEFAULT_TAGS:
        key, separator, value = expression.partition("=")
        if not key or any(character in key for character in '[]"'):
            raise ValueError(f"Invalid OSM tag key: {key}")
        if separator:
            clauses.append(f'  nwr["name"]["{_escape(key)}"~"{_escape(value)}"](area.searchArea);')
        else:
            clauses.append(f'  nwr["name"]["{_escape(key)}"](area.searchArea);')
    return f'''[out:json][timeout:{int(timeout_seconds)}];
area["boundary"="administrative"]["name"~"{_escape(area_name)}",i]->.searchArea;
(
{chr(10).join(clauses)}
);
out center tags meta;'''


def fetch_business_objects(endpoint: str | None = None, retries: int = 3, area_name: str = "Surakarta", tags: list[str] | None = None, timeout_seconds: float | None = None) -> list[dict[str, Any]]:
    url = endpoint or os.getenv("OVERPASS_ENDPOINT", DEFAULT_ENDPOINT)
    timeout = timeout_seconds or float(os.getenv("OVERPASS_TIMEOUT_SECONDS", "90"))
    query = build_query(area_name=area_name, tags=tags, timeout_seconds=min(int(timeout), 180))
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = requests.post(
                url,
                data={"data": query},
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            return payload.get("elements", [])
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt < retries - 1:
                time.sleep(2**attempt)
    raise RuntimeError(f"Overpass request failed after {retries} attempts: {last_error}")
