import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / "output" / "pdf-parser" / "direktori-industri-manufaktur-kabupaten-kendal-2025.json"
data = json.loads(path.read_text(encoding="utf-8"))

print("=== STRUKTUR ROOT ===")
if isinstance(data, dict):
    print("Root keys:", list(data.keys()))
elif isinstance(data, list):
    print("Root type: list")
    print("Jumlah elemen:", len(data))
    if data:
        print("Keys elemen pertama:",
              list(data[0].keys()) if isinstance(data[0], dict) else type(data[0]))

terms = [
    "JAVA MANDIRI INDONESIA",
    "MERAK JAYA BETON",
    "BORINE TECHNOLOGY INDONESIA",
    "SASAKURA INDONESIA",
    "NAHDIA KARYA",
]

def walk(node, path="$"):
    if isinstance(node, dict):
        content = node.get("content")
        if isinstance(content, str):
            upper = content.upper()
            if any(term in upper for term in terms):
                print(f"\n=== MATCH: {path} ===")
                print(json.dumps(node, ensure_ascii=False, indent=2)[:3500])

        for key, value in node.items():
            walk(value, f"{path}.{key}")

    elif isinstance(node, list):
        for index, item in enumerate(node):
            walk(item, f"{path}[{index}]")

print("\n=== ELEMEN YANG MEMUAT NAMA PERUSAHAAN ===")
walk(data)
