import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from backend.ai_curation import (
    FIELDS,
    MAX_BATCH_CANDIDATE_CHARS,
    _candidate_batches,
    _candidate_prompt_data,
    _parse_json_content,
    _json_response,
    curate_candidates,
    load_and_curate,
)


class AiCurationTests(unittest.TestCase):
    def test_parse_json_content_accepts_fenced_json(self) -> None:
        self.assertEqual(_parse_json_content('```json\n{"candidates": []}\n```'), {"candidates": []})

    def test_parse_json_content_reports_truncated_json(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Respons kemungkinan terpotong"):
            _parse_json_content('{"candidates":[{"company_name":"MEGA DAYA ABADI, CV",')

    @patch("backend.ai_curation.requests.post")
    def test_json_response_reports_provider_token_limit(self, post: Mock) -> None:
        response = Mock(ok=True)
        response.json.return_value = {
            "choices": [{"finish_reason": "length", "message": {"content": '{"candidates": ['}}]
        }
        post.return_value = response

        with self.assertRaisesRegex(RuntimeError, "terpotong karena batas token"):
            _json_response({"endpoint": "http://localhost:1234", "model": "test", "token": ""}, "{}")

    @patch("backend.ai_curation._settings")
    @patch("backend.ai_curation._json_response")
    def test_curate_candidates_preserves_every_candidate_and_prevents_rejection(
        self, json_response: Mock, settings: Mock
    ) -> None:
        settings.return_value = {"batch_size": 10, "concurrency": 1, "confidence": 0.75, "ruleset": "old rules", "web_lookup": False}
        json_response.return_value = {"candidates": [
            {"candidate_id": "a", "curation_status": "rejected", "company_name": "Contoh", "field_validation": {}},
            {"candidate_id": "b", "curation_status": "review", "company_name": "Belum jelas", "field_validation": {}},
        ], "rejected": 2, "field_issues": 0}
        candidates = [
            {"candidate_id": "a", "source_index": 1, "company_name": "Contoh", "evidence": "Contoh PT, Kendal"},
            {"candidate_id": "b", "source_index": 2, "company_name": "Belum jelas", "evidence": ""},
        ]

        curated, summary = curate_candidates(candidates)

        self.assertEqual([item["candidate_id"] for item in curated], ["a", "b"])
        self.assertEqual([item["curation_status"] for item in curated], ["review", "review"])
        self.assertEqual(summary["accepted"], 2)
        self.assertEqual(curated[0]["evidence"], "Contoh PT, Kendal")
        self.assertEqual(list(curated[0]), [*FIELDS, "candidate_id", "source_index", "curation_status", "field_validation"])
        self.assertNotIn("raw_data", curated[0])
        self.assertNotIn("extracted_data", curated[0])
        prompt = json_response.call_args.args[1]
        prompt_data = json.loads(prompt)
        self.assertIn("investment_type", prompt)
        self.assertIn("district", prompt)
        self.assertEqual(len(prompt_data["candidates"]), 2)
        self.assertNotIn("raw_data", json.dumps(prompt_data["candidates"]))
        self.assertNotIn("extracted_data", json.dumps(prompt_data["candidates"]))

    def test_prompt_compacts_redundant_data_and_splits_large_batches(self) -> None:
        candidates = [
            {
                "candidate_id": f"candidate-{index}",
                "source_index": index,
                "company_name": f"Company {index}",
                "evidence": f"Company {index} " + ("evidence " * 300),
                "raw_data": {"source_text": "duplicated source"},
                "extracted_data": {"company_name": f"Company {index}"},
            }
            for index in range(30)
        ]

        compact = _candidate_prompt_data(candidates[0])
        batches = _candidate_batches(candidates, 200)

        self.assertLessEqual(len(compact["evidence"]), 1602)
        self.assertTrue(compact["evidence"].startswith("Company 0"))
        self.assertGreater(len(batches), 1)
        for _, batch in batches:
            batch_size = sum(
                len(json.dumps(_candidate_prompt_data(candidate), ensure_ascii=False, separators=(",", ":")))
                for candidate in batch
            ) + max(0, len(batch) - 1) + 2
            self.assertLessEqual(batch_size, MAX_BATCH_CANDIDATE_CHARS)

    @patch("backend.ai_curation._settings")
    @patch("backend.ai_curation._json_response")
    def test_timeout_splits_batch_and_keeps_all_candidates(self, json_response: Mock, settings: Mock) -> None:
        settings.return_value = {
            "batch_size": 5, "concurrency": 1, "confidence": 0.75,
            "ruleset": "", "web_lookup": False,
        }
        json_response.side_effect = [
            RuntimeError("AI curation timed out after 60 seconds."),
            {"candidates": [{"candidate_id": "a", "company_name": "A", "curation_status": "accepted"}]},
            {"candidates": [{"candidate_id": "b", "company_name": "B", "curation_status": "accepted"}]},
        ]

        curated, summary = curate_candidates([
            {"candidate_id": "a", "source_index": 1, "company_name": "Old A", "evidence": "Evidence A"},
            {"candidate_id": "b", "source_index": 2, "company_name": "Old B", "evidence": "Evidence B"},
        ])

        self.assertEqual([item["company_name"] for item in curated], ["A", "B"])
        self.assertEqual([item["candidate_id"] for item in curated], ["a", "b"])
        self.assertTrue(summary["batch_timings"][0]["split_after_capacity_error"])
        self.assertEqual(json_response.call_count, 3)

    @patch("backend.ai_curation._settings")
    @patch("backend.ai_curation._json_response")
    def test_load_and_curate_writes_flat_json_artifact(self, json_response: Mock, settings: Mock) -> None:
        settings.return_value = {
            "batch_size": 5, "concurrency": 1, "confidence": 0.75,
            "ruleset": "", "web_lookup": False,
        }
        json_response.return_value = {"candidates": [{
            "candidate_id": "source-4",
            "source_index": 4,
            "company_name": "Clean Company",
            "curation_status": "accepted",
            "field_validation": {},
        }]}
        candidate = {
            "candidate_id": "source-4",
            "source_index": 4,
            "company_name": "Raw Company",
            "evidence": "Source evidence",
            "raw_data": {"source_text": "Source evidence"},
            "extracted_data": {"company_name": "Raw Company"},
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "raw.json"
            target = Path(directory) / "curated.json"
            source.write_text(json.dumps([candidate]), encoding="utf-8")

            load_and_curate(source, target)
            payload = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["company_name"], "Clean Company")
        self.assertEqual(payload[0]["evidence"], "Source evidence")
        self.assertEqual(list(payload[0]), [*FIELDS, "candidate_id", "source_index", "curation_status", "field_validation"])


if __name__ == "__main__":
    unittest.main()
