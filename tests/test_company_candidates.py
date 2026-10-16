import unittest

from backend.pdf_tools.extract_company_candidates import clean_business_sector, extract_phone_numbers, extract


class CompanyCandidateExtractionTests(unittest.TestCase):
    def test_extracts_multiple_indonesian_phone_numbers(self) -> None:
        self.assertEqual(
            extract_phone_numbers(["0271- 711037 0271 – 719641"]),
            "0271-711037; 0271-719641",
        )

    def test_cleans_sector_classification_number(self) -> None:
        self.assertEqual(clean_business_sector("KRUPUK SALA (10)"), "KRUPUK SALA")
        self.assertEqual(clean_business_sector("KBLI: KRUPUK SALA (13)"), "KRUPUK SALA")

    def test_hotel_directory_accepts_numbered_names_without_legal_entity(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            markdown = root / "hotel.md"
            output = root / "candidates.json"
            csv_output = root / "candidates.csv"
            markdown.write_text("# DIREKTORI HOTEL DAN AKOMODASI DI KOTA SURAKARTA\n1. HOTEL BINTANG SOLO\nJl. Slamet Riyadi No. 1\n2. PENGINAPAN MELATI\nJl. Adi Sucipto No. 2\n", encoding="utf-8")
            records = extract(None, str(markdown), str(output), str(csv_output), "", "Jawa Tengah", "Kota Surakarta", "")

        self.assertEqual([record["company_name"] for record in records], ["HOTEL BINTANG SOLO", "PENGINAPAN MELATI"])
        self.assertEqual(records[0]["candidate_id"], "source-1")
        self.assertEqual(records[0]["business_sector"], "Hotel dan akomodasi")


if __name__ == "__main__":
    unittest.main()

