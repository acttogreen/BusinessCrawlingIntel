import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / "output" / "pdf-parser" / "direktori-industri-manufaktur-kabupaten-kendal-2025.json"

data = json.loads(path.read_text(encoding="utf-8"))
counts = Counter()
samples = []
pages = Counter()

def walk(node):
    if isinstance(node, dict):
        kind = node.get("type")
        if kind:
            counts[kind] += 1

        page = node.get("page number")
        if page is not None and kind:
            pages[page] += 1

        content = node.get("content")
        if isinstance(content, str) and content.strip():
            if len(samples) < 40:
                samples.append((page, kind, content.strip().replace("\n", " ")[:180]))

        for value in node.values():
            walk(value)

    elif isinstance(node, list):
        for item in node:
            walk(item)

walk(data)

print("\n=== JUMLAH ELEMEN ===")
for kind, count in counts.most_common():
    print(f"{kind:20} {count}")

print("\n=== CONTOH TEKS YANG DIEKSTRAK ===")
for page, kind, content in samples:
    print(f"[Halaman {page} | {kind}] {content}")

print("\n=== HALAMAN DENGAN ELEMEN PALING SEDIKIT ===")
for page, count in sorted(pages.items(), key=lambda item: item[1])[:15]:
    print(f"Halaman {page}: {count} elemen")
