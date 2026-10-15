from pathlib import Path
import opendataloader_pdf

ROOT = Path(__file__).resolve().parents[2]
pdf_path = ROOT / "document" / "Jawa Tengah" / "Kendal" / "direktori-industri-manufaktur-kabupaten-kendal-2025.pdf"
output_dir = ROOT / "output" / "pdf-parser"

if not pdf_path.is_file():
    raise FileNotFoundError(f"PDF tidak ditemukan: {pdf_path}")

output_dir.mkdir(parents=True, exist_ok=True)

print(f"Input : {pdf_path}")
print(f"Output: {output_dir}")
print("Memulai parsing PDF...")

opendataloader_pdf.convert(
    input_path=[str(pdf_path.resolve())],
    output_dir=str(output_dir.resolve()),
    format="json,markdown",
)

print("Parsing selesai.")
print(f"Periksa hasil di: {output_dir}")
