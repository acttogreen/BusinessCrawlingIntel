import unittest

from backend.legal_crawler import enrich_records
from backend.normalizer import normalize_element


class LegalCrawlerTests(unittest.TestCase):
    def test_enrichment_follows_only_same_domain_and_records_unverified_clue(self) -> None:
        pages = {
            "https://example.test/": '<a href="/legal">Legal</a><a href="https://other.test/privacy">Privacy</a>',
            "https://example.test/legal": "<footer>PT Surakarta Kuliner Indonesia</footer>",
        }
        visited: list[str] = []
        record = {
            "id": "osm:node:1",
            "contact": {"website": "https://example.test/"},
            "legal": {"status": "unknown"},
        }

        attempted, updated = enrich_records(
            [record],
            fetcher=lambda url: visited.append(url) or pages.get(url),
        )

        self.assertEqual((attempted, updated), (1, 1))
        self.assertEqual(visited, ["https://example.test/", "https://example.test/legal"])
        self.assertEqual(record["legal"]["status"], "unverified")
        self.assertEqual(record["legal"]["entity_name"], "PT Surakarta Kuliner Indonesia")
        self.assertEqual(record["legal"]["evidence"][0]["source"], "business_website")

    def test_osm_normalization_preserves_existing_legal_and_investment(self) -> None:
        previous = {
            "id": "osm:node:1",
            "legal": {"status": "unverified", "entity_name": "PT Contoh"},
            "investment": {"status": "unknown"},
            "metadata": {"first_seen_at": "2026-01-01T00:00:00+00:00"},
        }

        normalized = normalize_element(
            {"type": "node", "id": 1, "lat": -7.57, "lon": 110.82, "tags": {"name": "Contoh", "shop": "supermarket"}},
            previous,
        )

        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["legal"], previous["legal"])
        self.assertEqual(normalized["investment"], previous["investment"])


if __name__ == "__main__":
    unittest.main()