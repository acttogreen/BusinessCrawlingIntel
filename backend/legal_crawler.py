import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests

from backend.storage import read_businesses, write_businesses


USER_AGENT = "SurakartaBusinessIntelligence/0.1 (legal enrichment; local research prototype)"
LEGAL_LINK_WORDS = ("legal", "privacy", "about", "tentang", "syarat", "terms", "contact", "kontak")
ENTITY_PATTERN = re.compile(
    r"\b(?P<name>(?:PT\.?|CV\.?|Perseroan Terbatas|Commanditaire Vennootschap|Yayasan|Koperasi|Perumda|Persero)\s+[^.!?\n]{1,100})",
    re.IGNORECASE,
)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._ignored_depth = 0
        self._active_href: str | None = None
        self._active_anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
        if tag == "a":
            self._active_href = attributes.get("href")
            self._active_anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "a" and self._active_href:
            label = " ".join(self._active_anchor_text).strip()
            self.links.append((self._active_href, label))
            self._active_href = None
            self._active_anchor_text = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if not value or self._ignored_depth:
            return
        self.text.append(value)
        if self._active_href is not None:
            self._active_anchor_text.append(value)


def _fetch_html(url: str) -> str | None:
    try:
        with requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=(4, 12),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200 or "text/html" not in response.headers.get("Content-Type", "").lower():
                return None
            body = bytearray()
            for chunk in response.iter_content(chunk_size=16_384):
                body.extend(chunk)
                if len(body) > 1_000_000:
                    return None
            return body.decode(response.encoding or "utf-8", errors="replace")
    except requests.RequestException:
        return None


def _legal_entity(text: str) -> dict[str, str] | None:
    normalized = re.sub(r"\s+", " ", text)
    match = ENTITY_PATTERN.search(normalized)
    if not match:
        return None
    name = match.group("name").strip(" .,:;-|")
    prefix = re.match(r"(?:PT\.?|CV\.?|Perseroan Terbatas|Commanditaire Vennootschap|Yayasan|Koperasi|Perumda|Persero)", name, re.IGNORECASE)
    if not prefix:
        return None
    entity_type = re.sub(r"\.$", "", prefix.group(0)).upper()
    return {"entity_name": name, "entity_type": entity_type, "excerpt": normalized[max(0, match.start() - 80):match.end() + 80]}


def crawl_website(
    website_url: str,
    fetcher: Callable[[str], str | None] = _fetch_html,
    max_pages: int = 4,
) -> list[dict[str, str]]:
    parsed_origin = urlparse(website_url)
    if parsed_origin.scheme not in {"http", "https"} or not parsed_origin.netloc or parsed_origin.username or parsed_origin.password:
        return []

    origin = parsed_origin.netloc.lower()
    pending = [website_url]
    visited: set[str] = set()
    evidence: list[dict[str, str]] = []

    while pending and len(visited) < max(1, min(max_pages, 8)):
        current_url = pending.pop(0)
        parsed_url = urlparse(current_url)
        if parsed_url.netloc.lower() != origin or parsed_url.scheme not in {"http", "https"}:
            continue
        if current_url in visited:
            continue
        visited.add(current_url)
        html = fetcher(current_url)
        if not html:
            continue

        parser = _PageParser()
        parser.feed(html)
        result = _legal_entity(" ".join(parser.text))
        if result:
            evidence.append({"url": current_url, **result})

        candidates = []
        for href, label in parser.links:
            target = urljoin(current_url, href)
            parsed_target = urlparse(target)
            if parsed_target.netloc.lower() != origin or parsed_target.scheme not in {"http", "https"}:
                continue
            hint = f"{label} {parsed_target.path}".lower()
            if any(word in hint for word in LEGAL_LINK_WORDS):
                candidates.append(target)
        pending.extend(url for url in candidates if url not in visited and url not in pending)

    return evidence


def enrich_records(
    records: list[dict],
    max_pages: int = 4,
    limit: int | None = None,
    fetcher: Callable[[str], str | None] = _fetch_html,
) -> tuple[int, int]:
    updated = 0
    attempted = 0
    candidates = records[:limit] if limit is not None else records
    checked_at = datetime.now(timezone.utc).isoformat()

    for record in candidates:
        legal = record.setdefault("legal", {"status": "unknown"})
        if legal.get("status") == "verified":
            continue
        website = (record.get("contact") or {}).get("website")
        if not website:
            continue
        attempted += 1
        findings = crawl_website(website, fetcher=fetcher, max_pages=max_pages)
        if not findings:
            continue

        first_finding = findings[0]
        legal["status"] = "unverified"
        legal["entity_name"] = first_finding["entity_name"]
        legal["entity_type"] = first_finding["entity_type"]
        legal["checked_at"] = checked_at
        evidence = legal.setdefault("evidence", [])
        known = {(item.get("url"), item.get("excerpt")) for item in evidence}
        for finding in findings:
            item = {**finding, "source": "business_website", "observed_at": checked_at}
            if (item["url"], item["excerpt"]) not in known:
                evidence.append(item)
                known.add((item["url"], item["excerpt"]))
        updated += 1

    return attempted, updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Find unverified legal-entity clues on OSM-listed business websites")
    parser.add_argument("--write", action="store_true", help="Write enrichment results to businesses.json; otherwise only report")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of businesses to inspect")
    parser.add_argument("--max-pages", type=int, default=4, help="Maximum same-site HTML pages per business (1-8)")
    args = parser.parse_args()

    records = read_businesses()
    attempted, updated = enrich_records(records, max_pages=args.max_pages, limit=args.limit)
    if args.write:
        write_businesses(records)
    print(f"Businesses inspected: {attempted}")
    print(f"Businesses with legal clues: {updated}")
    print(f"JSON updated: {'yes' if args.write else 'no (dry run)'}")


if __name__ == "__main__":
    main()