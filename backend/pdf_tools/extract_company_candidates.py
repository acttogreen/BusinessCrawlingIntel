"""Defensive PDF layout/Markdown company candidate extractor."""
import argparse
import csv
import json
import re
from pathlib import Path

FIELDS = ["company_name", "legal_entity", "address", "district", "city", "province", "business_sector", "source_url", "evidence", "investment_type", "phone_number"]
LEGAL = r"PT|CV|UD|PD|BLU|YAYASAN|PERORANGAN|PERSERO"
LEGAL = r"PT|CV|UD|PO|PD|BLU|YAYASAN|KOPERASI|PERORANGAN|PERSERO"
DISTRICTS = ("Laweyan", "Serengan", "Pasar Kliwon", "Jebres", "Banjarsari")
ADDRESS_MARKER = re.compile(r"\b(?:Jl\.?|Jalan|Dukuh|Gedung|Kampung|Kp\.?|Rt\.?|Rw\.?|Desa|Kel\.?|Kelurahan|Kec\.?|Kecamatan|Kab\.?|Kabupaten|No\.?)\b|\b\d{5}\b", re.I)
NON_COMPANY = re.compile(r"(?:di dalam tiap kelompok|in each group|petunjuk|instruksi|metodologi|dikategorikan|sebagaimana|sedangkan|urut|halaman|lanjutan|daftar isi|kata pengantar)", re.I)
LEGAL_ONLY = re.compile(r"\b(?:PT|CV|UD|PO|PD|BLU|YAYASAN|KOPERASI|PERORANGAN|PERSERO)\b", re.I)
DISTRICTS = ("Laweyan", "Serengan", "Pasar Kliwon", "Jebres", "Banjarsari")

def text_of(item):
    return str(item.get("content") or item.get("text") or "").strip() if isinstance(item, dict) else ""

def layout_lines(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    nodes = payload if isinstance(payload, list) else payload.get("elements", []) if isinstance(payload, dict) else []
    if not isinstance(nodes, list): return []
    def sort_key(item):
        box = item.get("bounding box", item.get("bounding_box", item.get("bbox", {}))) if isinstance(item, dict) else {}
        if isinstance(box, list): left, top = (box[0] if box else 0), (box[1] if len(box) > 1 else 0)
        else: left, top = box.get("left", box.get("x", 0)), box.get("top", box.get("y", 0))
        return (item.get("page number", item.get("page", 0)) if isinstance(item, dict) else 0, top or 0, left or 0)
    return [text_of(item) for item in sorted((item for item in nodes if text_of(item)), key=sort_key)]

def clean_name(raw):
    raw = re.sub(r"\s+", " ", raw).strip(" :-")
    match = re.search(r",?\s*\b(" + LEGAL + r")\.?\s*(?=$|(?:Jl\.?|Jalan|Dukuh|Gedung|Kampung|Kp\.?|Rt\.?|Rw\.?|Desa|Kel\.?|Kec\.?|Kab\.?|No\.?|\d{5}))", raw, re.I)
    if match:
        name, entity = raw[:match.start()].rstrip(" ,"), match.group(1).upper()
        trailing_address = raw[match.end():].strip(" ,.-")
    else:
        trailing_address = ""
        match = re.match(r"^\b(" + LEGAL + r")\.?\s+(.+)$", raw, re.I)
        name, entity = (match.group(2).strip(), match.group(1).upper()) if match else (raw, "")
    address = trailing_address
    marker = ADDRESS_MARKER.search(name)
    if marker and marker.start() > 2:
        address, name = name[marker.start():].strip(" ,.-"), name[:marker.start()].strip(" ,.-")
    return name, entity, address


def valid_company_name(name, entity=""):
    if len(name) < 3 or len(name) > 180 or NON_COMPANY.search(name): return False
    if entity or LEGAL_ONLY.search(name): return True
    words = name.split()
    return len(words) <= 8 and not re.search(r"[.!?]", name) and not re.search(r"\b(?:perusahaan|establishment|kelompok|menurut|adalah)\b", name, re.I)

def extract(input_json, input_markdown, output_json, output_csv, source_url, province, city, investment_type):
    lines = layout_lines(input_json) if input_json else []
    if not lines and input_markdown and Path(input_markdown).exists():
        lines = [re.sub(r"^#{1,6}\s*", "", line).strip() for line in Path(input_markdown).read_text(encoding="utf-8").splitlines() if line.strip()]
    records, seen = [], set()
    for index, line in enumerate(lines):
        raw = re.sub(r"^#{2,6}\s+", "", line).strip()
        if not re.match(r"^#{2,6}\s+", line) and not re.search(r"\b(?:PT|CV|UD|PO|PD|BLU|YAYASAN|KOPERASI|PERSERO)\b", raw, re.I): continue
        if re.match(r"^(KBLI|DIREKTORI|DAFTAR|KATA PENGANTAR|PREFACE|PENJELASAN|TABLE OF CONTENTS)", raw, re.I): continue
        name, entity, inline_address = clean_name(raw)
        if not valid_company_name(name, entity) or name.casefold() in seen: continue
        context = lines[index + 1:index + 7]; combined = " ".join(context)
        address = inline_address or next((x for x in context if ADDRESS_MARKER.search(x)), "")
        district = next((d for d in DISTRICTS if re.search(r"\b" + re.escape(d) + r"\b", combined, re.I)), "")
        phone_match = next((re.search(r"(?:\\+62|0)(?:[ -]?\\d){7,14}", x) for x in context if re.search(r"(?:\\+62|0)(?:[ -]?\\d){7,14}", x)), None)
        sector = next((x for x in context if re.search(r"\bKBLI\b|\(\d{2}\)", x, re.I)), "")
        seen.add(name.casefold()); records.append(dict(zip(FIELDS, [name, entity, address, district, city, province, sector, source_url, " ".join([raw] + context), investment_type, phone_match.group(0) if phone_match else ""])))
    Path(output_json).parent.mkdir(parents=True, exist_ok=True); Path(output_json).write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    with Path(output_csv).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS); writer.writeheader(); writer.writerows(records)
    return records

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--input-json"); parser.add_argument("--input-markdown"); parser.add_argument("--output-json", required=True); parser.add_argument("--output-csv", required=True); parser.add_argument("--source-url", default=""); parser.add_argument("--province", default="Central Java"); parser.add_argument("--city", default="Surakarta"); parser.add_argument("--investment-type", default="PMDN"); args = parser.parse_args()
    print(f"Kandidat ditemukan: {len(extract(args.input_json, args.input_markdown, args.output_json, args.output_csv, args.source_url, args.province, args.city, args.investment_type))}")
if __name__ == "__main__": main()
