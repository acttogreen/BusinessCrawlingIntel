"""Defensive PDF layout/Markdown company candidate extractor."""
import argparse
import csv
import json
import re
from pathlib import Path

FIELDS = ["company_name", "legal_entity", "address", "district", "city", "province", "business_sector", "source_url", "evidence", "investment_type", "phone_number"]
LEGAL = r"PT|CV|UD|PD|BLU|YAYASAN|PERORANGAN|PERSERO"
LEGAL = r"PT|CV|UD|PO|PD|BLU|YAYASAN|KOPERASI|PERORANGAN|PERSERO"
HOTEL_MARKER = re.compile(r"\b(?:hotel|akomodasi|penginapan|losmen|resort|guest\s*house|homestay)\b", re.I)
HOTEL_HEADER = re.compile(r"\b(?:direktori|daftar)\b.*\b(?:hotel|akomodasi|penginapan)\b|\b(?:hotel|akomodasi|penginapan)\b.*\b(?:direktori|daftar)\b", re.I)
HOTEL_NAME_NOISE = re.compile(r"^(?:no|nomor|nama|alamat|kecamatan|kelurahan|jumlah|kamar|klasifikasi|bintang|halaman|sumber)\b", re.I) 
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

PHONE_PATTERN = re.compile(r"(?<!\d)(?:0\d{2,4}|\+62\s?\d{2,4})\s*[-–—]?\s*\d(?:[\s-]*\d){5,10}(?=\s+(?:0|\+62)|\s*$)")

def extract_phone_numbers(lines):
    numbers = []
    for line in lines:
        for match in PHONE_PATTERN.finditer(line):
            value = re.sub(r"\s+", "", match.group(0)).replace("–", "-").replace("—", "-")
            value = re.sub(r"(?<=\d)-+", "-", value)
            digits = re.sub(r"\D", "", value)
            if 8 <= len(digits) <= 14 and value not in numbers:
                numbers.append(value)
    return "; ".join(numbers)


def clean_business_sector(raw):
    value = re.sub(r"\bKBLI\s*[:\-]?\s*", "", raw, flags=re.I)
    value = re.sub(r"\s*\(\s*\d+(?:\.\d+)?\s*\)", "", value)
    value = re.sub(r"\s+", " ", value).strip(" ,;:-")
    return value

def extract(input_json, input_markdown, output_json, output_csv, source_url, province, city, investment_type):
    lines = layout_lines(input_json) if input_json else []
    if not lines and input_markdown and Path(input_markdown).exists():
        lines = [re.sub(r"^#{1,6}\s*", "", line).strip() for line in Path(input_markdown).read_text(encoding="utf-8").splitlines() if line.strip()]
    records, seen = [], set()
    document_text = " ".join(lines[:80])
    hotel_document = bool(HOTEL_HEADER.search(document_text) or (HOTEL_MARKER.search(document_text) and re.search(r"\b(?:surakarta|akomodasi)\b", document_text, re.I)))
    for index, line in enumerate(lines):
        raw = re.sub(r"^#{2,6}\s+", "", line).strip()
        context = lines[index + 1:index + 7]
        numbered_hotel_row = hotel_document and bool(re.match(r"^\s*\d{1,3}[.)\s-]+", raw))
        hotel_name_row = hotel_document and bool(HOTEL_MARKER.search(raw)) and not HOTEL_NAME_NOISE.search(raw)
        legal_company_row = bool(re.search(r"\b(?:PT|CV|UD|PO|PD|BLU|YAYASAN|KOPERASI|PERSERO)\b", raw, re.I))
        markdown_heading = bool(re.match(r"^#{2,6}\s+", line))
        if not (markdown_heading or legal_company_row or numbered_hotel_row or hotel_name_row):
            continue
        if re.match(r"^(KBLI|DIREKTORI|DAFTAR|KATA PENGANTAR|PREFACE|PENJELASAN|TABLE OF CONTENTS)", raw, re.I):
            continue
        raw = re.sub(r"^\s*\d{1,3}[.)\s-]+", "", raw).strip(" :-")
        name, entity, inline_address = clean_name(raw)
        if hotel_document and numbered_hotel_row and not entity:
            name = re.sub(r"\s+", " ", name).strip(" ,.-")
        if not valid_company_name(name, entity) or name.casefold() in seen:
            continue
        combined = " ".join(context)
        address = inline_address or next((x for x in context if ADDRESS_MARKER.search(x)), "")
        district = next((d for d in DISTRICTS if re.search(r"\b" + re.escape(d) + r"\b", combined, re.I)), "")
        phone_number = extract_phone_numbers(context)
        sector_raw = next((x for x in context if re.search(r"\bKBLI\b|\(\d{2}\)", x, re.I)), "")
        sector = clean_business_sector(sector_raw) or ("Hotel dan akomodasi" if hotel_document else "")
        seen.add(name.casefold())
        evidence = " ".join([raw] + context)
        extracted = dict(zip(FIELDS, [name, entity, address, district, city, province, sector, source_url, evidence, investment_type, phone_number]))
        candidate_id = f"source-{index}"
        records.append({**extracted, "candidate_id": candidate_id, "source_index": index, "extracted_data": dict(extracted), "raw_data": {"candidate_id": candidate_id, "source_index": index, "source_text": evidence, "source_line": raw, "context_lines": context}})
    Path(output_json).parent.mkdir(parents=True, exist_ok=True); Path(output_json).write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    with Path(output_csv).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore"); writer.writeheader(); writer.writerows(records)
    return records

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--input-json"); parser.add_argument("--input-markdown"); parser.add_argument("--output-json", required=True); parser.add_argument("--output-csv", required=True); parser.add_argument("--source-url", default=""); parser.add_argument("--province", default="Central Java"); parser.add_argument("--city", default="Surakarta"); parser.add_argument("--investment-type", default="PMDN"); args = parser.parse_args()
    print(f"Kandidat ditemukan: {len(extract(args.input_json, args.input_markdown, args.output_json, args.output_csv, args.source_url, args.province, args.city, args.investment_type))}")
if __name__ == "__main__": main()
