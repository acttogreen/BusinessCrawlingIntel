import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / "output" / "pdf-parser" / "direktori-industri-manufaktur-kabupaten-kendal-2025.json"
data = json.loads(path.read_text(encoding="utf-8"))

target_pages = {24, 40, 46, 54, 56}

print("Urutan berikut mengikuti urutan elemen dalam JSON.")
print("bbox = [x_min, y_min, x_max, y_max]\n")

for index, node in enumerate(data.get("kids", [])):
    if not isinstance(node, dict):
        continue

    page = node.get("page number")
    if page not in target_pages:
        continue

    content = " ".join(str(node.get("content", "")).split())
    if not content:
        continue

    bbox = node.get("bounding box", [])
    kind = node.get("type", "?")
    element_id = node.get("id", "?")

    print(
        f"PAGE={page:02} JSON_INDEX={index:03} "
        f"ID={element_id:03} TYPE={kind}"
    )
    print(f"  BBOX={bbox}")
    print(f"  TEXT={content[:300]}")
