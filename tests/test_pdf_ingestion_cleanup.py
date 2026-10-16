import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.pdf_ingestion import remove_artifact_tree


class PdfIngestionCleanupTests(unittest.TestCase):
    def test_remove_artifact_tree_removes_nested_project_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_folder = root / "province" / "region" / "project_test"
            nested = project_folder / "document_test" / "original_images"
            nested.mkdir(parents=True)
            (nested / "image.png").write_bytes(b"artifact")
            (project_folder / "metadata.json").write_text("{}", encoding="utf-8")

            with patch("backend.pdf_ingestion.OUTPUT_ROOT", root):
                remove_artifact_tree(project_folder)

            self.assertFalse(project_folder.exists())

    def test_remove_artifact_tree_rejects_path_outside_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root.parent / f"{root.name}_outside"
            outside.mkdir()
            try:
                with patch("backend.pdf_ingestion.OUTPUT_ROOT", root):
                    with self.assertRaisesRegex(ValueError, "escapes"):
                        remove_artifact_tree(outside)
            finally:
                outside.rmdir()


if __name__ == "__main__":
    unittest.main()
