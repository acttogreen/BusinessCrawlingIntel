# 🏢 Surakarta Business Intelligence (BusinessCrawlingIntel)

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org)
[![React](https://img.shields.io/badge/React-18%2F19-61DAFB?style=flat&logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178C6?style=flat&logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![Vite](https://img.shields.io/badge/Vite-6.0+-646CFF?style=flat&logo=vite&logoColor=white)](https://vitejs.dev)
[![MapLibre GL](https://img.shields.io/badge/MapLibre-GL%20JS-396B94?style=flat&logo=maplibre&logoColor=white)](https://maplibre.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat&logo=docker&logoColor=white)](https://www.docker.com)

**BusinessCrawlingIntel** adalah platform intelijen bisnis lokal (*local-first business intelligence*) yang memadukan data registri resmi pemerintah (diekstraksi dari dokumen PDF direktori industri/perusahaan) dengan data geospasial faktual dari **OpenStreetMap (OSM)**, diperkaya dengan pipeline kurasi kecerdasan buatan (**AI Curation**) dan algoritma pencocokan entitas multi-tahap (*cascading entity resolution*).

Proyek ini awalnya difokuskan untuk memetakan ekosistem bisnis dan industri di wilayah **Kota Surakarta (Solo)** dan kawasan industri strategis di Jawa Tengah (seperti **Kabupaten Kendal**), serta dirancang secara modular untuk mendukung seluruh kabupaten/kota di Indonesia.

---

## 📑 Daftar Isi

- [Latar Belakang & Filosofi](#-latar-belakang--filosofi)
- [Arsitektur Sistem](#-arsitektur-sistem)
- [Fitur Utama](#-fitur-utama)
- [Teknologi yang Digunakan](#-teknologi-yang-digunakan)
- [Struktur Repositori](#-struktur-repositori)
- [Panduan Instalasi & Persiapan](#-panduan-instalasi--persiapan)
- [Cara Menjalankan Aplikasi](#-cara-menjalankan-aplikasi)
- [Pipeline Ekstraksi & Kurasi Dokumen (PDF)](#-pipeline-ekstraksi--kurasi-dokumen-pdf)
- [Koleksi Data OpenStreetMap & Pemetaan Entitas](#-koleksi-data-openstreetmap--pemetaan-entitas)
- [Daftar Endpoint API Utama](#-daftar-endpoint-api-utama)
- [Pengujian (Testing)](#-pengujian-testing)
- [Prinsip Integritas Data (Data Provenance)](#-prinsip-integritas-data-data-provenance)

---

## 💡 Latar Belakang & Filosofi

Seringkali terdapat jurang pemisah antara **data registri pemerintah** (yang biasanya tersimpan dalam direktori/laporan statis berformat PDF dengan data legalitas, status PMA/PMDN, dan nomor kontak) dengan **kondisi spasial faktual di lapangan** (yang tercatat secara kolaboratif di OpenStreetMap namun minim informasi legalitas formal).

**BusinessCrawlingIntel** hadir untuk menjembatani kedua sumber tersebut dengan prinsip:
1. **Local-First & Tanpa Ketergantungan Berlebih**: Dapat dijalankan sepenuhnya di komputer lokal menggunakan persistensi berbasis file JSON terstruktur dan terisolasi.
2. **Preservasi Provenance Data**: Asal-usul setiap data tidak pernah dihilangkan. Rekod membedakan data sumber resmi (bukti teks/URL) dan data hasil pencocokan OSM (`osm_type`, `osm_id`).
3. **Anti-Halusinasi Data**: Tidak pernah menebak atau memalsukan bentuk badan hukum (PT, CV, UD) atau status investasi (PMA/PMDN) jika tidak ada bukti eksplisit dalam dokumen resmi. Jika belum diverifikasi, status disetel sebagai `unknown`.
4. **Presisi Terminologi**: Membedakan antara *Perubahan Data Terkini (Recent Data Activity)* pada OSM dengan *Aktivitas Bisnis Nyata*.

---

## 🏗 Arsitektur Sistem

Alur kerja data dari ekstraksi hingga visualisasi interaktif di dashboard:

```text
┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│     Dokumen Direktori PDF       │       │    OpenStreetMap (Overpass)     │
│   (Laporan Pemda / Dinas / Kemen) │       │   (POI Bisnis, Toko, Kantor)    │
└────────────────┬────────────────┘       └────────────────┬────────────────┘
                 │                                         │
                 ▼                                         ▼
   [ Mesin Ekstraksi PDF ]                       [ Collector & Normalizer ]
   - OpenDataLoader (Java)                                 │
   - PyMuPDF / PyMuPDF4LLM (Python)                        │
                 │                                         ▼
                 ▼                               ┌───────────────────┐
     [ Kandidat Perusahaan ]                     │  businesses.json  │
   (Nama, Alamat, Kontak, Sektor)                │  activities.json  │
                 │                               └─────────┬─────────┘
                 ▼                                         │
       [ AI Curation Pipeline ]                            │
     - Validasi field & badan hukum                        │
     - OpenAI / Groq / Ollama / Local                      │
                 │                                         │
                 ▼                                         │
     [ Curated Candidates JSON ]                           │
                 │                                         │
                 └───────────────────┬─────────────────────┘
                                     │
                                     ▼
                       [ Cascading Entity Matching ]
                     - Normalisasi nama & legal affixes
                     - Fuzzy string matching (difflib)
                     - Spatial district centroid fallback
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │   business_database_mapping.json    │
                  │   (matched / review / unmatched)    │
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                       ┌───────────────────────────┐
                       │      FastAPI Backend      │
                       └─────────────┬─────────────┘
                                     │
                                     ▼
                     ┌───────────────────────────────┐
                     │   React + MapLibre Dashboard  │
                     │  - Peta Interaktif Spasial    │
                     │  - Multi-Filter & Search      │
                     │  - PDF Ingestion Studio       │
                     │  - Analitik & Visualisasi     │
                     │  - Ekspor CSV / Native Excel  │
                     └───────────────────────────────┘
```

---

## 🚀 Fitur Utama

### 1. Peta Geospasial & Visualisasi Interaktif
- **Peta Vektor/Raster MapLibre GL JS**: Render peta cepat dan responsif dengan integrasi tile OpenStreetMap.
- **Marker Dinamis Berbasis Metode Pencocokan**:
  - 🟠 **Coral**: Pencocokan langsung dengan POI OpenStreetMap (*Direct OSM Match*).
  - 🟢 **Teal**: Hasil *Geocoding* berbasis alamat atau kelurahan/kecamatan.
  - 🟣 **Purple**: Estimasi titik area representatif (*Synthetic Visual Marker* untuk wilayah/kawasan industri).
- **Fly-to Interaction**: Navigasi mulus ke koordinat saat entitas bisnis dipilih dari daftar atau tabel.

### 2. Multi-Filter & Eksplorasi Data Cepat
- **Filter Wilayah Hierarkis**: Navigasi antar-provinsi dan kabupaten/kota (misal: Kota Surakarta, Kabupaten Kendal).
- **Filter Sektor Bisnis**: Filter kategori makro dan subsektor spesifik.
- **Filter Bentuk Badan Hukum**: Pengelompokan PT, CV, UD, Koperasi, Yayasan, Perum, dll.
- **Filter Status Investasi**: Klasifikasi PMDN (Penanaman Modal Dalam Negeri) dan PMA (Penanaman Modal Asing).
- **Filter Status Pemetaan OSM**: Menampilkan bisnis yang sudah terpetakan (*matched*) atau belum terpetakan (*unmatched*).
- **Filter Tahun Berdiri & Resensi Aktivitas**: Deteksi rekod berdasarkan tahun berdiri serta perubahan data OSM (7, 30, 90, 365 hari terakhir).

### 3. PDF Ingestion & Extraction Studio
- **Pengelolaan Proyek Multi-Dokumen**: Buat proyek pengolahan dokumen berbasis wilayah (provinsi dan kabupaten/kota).
- **Pilihan Mesin Ekstraksi (Dual Extractor)**:
  - **OpenDataLoader PDF**: Engine berbasis Java/JAR untuk tata letak dokumen formal dan tabel kompleks.
  - **PyMuPDF + PyMuPDF4LLM**: Ekstraktor berbasis Python berperforma tinggi yang mengubah dokumen ke format Markdown terstruktur.
- **Pembersihan & Kandidat Perusahaan Otomatis**: Deteksi pola nama perusahaan, nomor telepon (termasuk multi-nomor Indonesia), alamat, sektor KBLI, dan bukti teks pendukung (*evidence*).
- **Tabel Editor Kandidat**: Fitur edit *inline* langsung di browser dan hapus baris yang tidak relevan dengan sinkronisasi instan ke JSON dan CSV.

### 4. Kurasi Berbasis Kecerdasan Buatan (AI Curation)
- **Dukungan Multi-Provider LLM**: Terintegrasi langsung dengan OpenAI, Groq, Together AI, Ollama, serta *endpoint* lokal kompatibel OpenAI.
- **Penyimpanan Token Terenkripsi**: Kunci API disimpan aman di sisi server menggunakan enkripsi simetris Fernet (AES-256).
- **Parameter Kurasi Kustom**: Pengaturan ukuran *batch*, batas *concurrency*, *timeout*, tingkat toleransi *confidence*, serta aturan prompt kurasi (*custom ruleset*).
- **Job Monitoring**: Pemrosesan kurasi berjalan di latar belakang (*background threading*) lengkap dengan progres bar status.

### 5. Analitik & Demografi Bisnis
- Modal statistik komprehensif menampilkan:
  - Diagram batang distribusi sektor industri.
  - Distribusi geografis per kecamatan.
  - *Pie chart* komposisi bentuk badan hukum (*legal entity demographics*).
  - Distribusi status investasi (PMA vs PMDN).

### 6. Ekspor Data Lengkap
- **Ekspor CSV**: Format standar UTF-8 dengan BOM agar terbaca sempurna di Microsoft Excel.
- **Ekspor Native XLSX**: Generator XML spreadsheet murni berkecepatan tinggi tanpa dependensi library Python berat.

### 7. Pengalaman Pengguna (UI/UX) Modern
- **Mode Dwibahasa**: Mendukung Bahasa Indonesia (ID) dan English (EN).
- **Mode Tema**: Tema Gelap (*Dark Mode*) yang elegan dan Tema Terang (*Light Mode*).
- **Responsif & Ringan**: Dibangun dengan Vanilla CSS terstruktur tanpa bloating framework CSS berlebih.

---

## 🛠 Teknologi yang Digunakan

### Backend
| Komponen | Teknologi | Deskripsi |
| :--- | :--- | :--- |
| **Framework** | [FastAPI](https://fastapi.tiangolo.com/) | RESTful API asynchronous berkinerja tinggi |
| **Server ASGI** | [Uvicorn](https://www.uvicorn.org/) | Server ASGI standar industri |
| **Data Engine** | Python 3.12, Pydantic | Validasi skema tipe data dan serialisasi |
| **PDF Extraction** | PyMuPDF, PyMuPDF4LLM, OpenDataLoader | Parsing tabel dan dokumen PDF ke JSON/Markdown |
| **Enkripsi** | Cryptography (Fernet) | Enkripsi kredensial API Key lokal |
| **OSM Client** | Requests, Overpass API | Query Overpass QL untuk POI spasial |

### Frontend
| Komponen | Teknologi | Deskripsi |
| :--- | :--- | :--- |
| **Library UI** | [React](https://react.dev/) + [TypeScript](https://www.typescriptlang.org/) | Antarmuka komponen modular dan type-safe |
| **Build Tool** | [Vite](https://vitejs.dev/) | HMR kilat dan bundler modern |
| **Peta Spasial** | [MapLibre GL JS](https://maplibre.org/) | Rendering peta WebGL sumber terbuka |
| **Styling** | Vanilla CSS Modern | Desain kustom elegan, responsive, dan theme-aware |

---

## 📂 Struktur Repositori

```text
BusinessCrawlingIntel/
├── AGENT.md                 # Prinsip rekayasa, aturan data, dan panduan teknis proyek
├── Dockerfile               # Multi-stage Docker build (Frontend dist + FastAPI backend)
├── render.yaml              # Konfigurasi deployment PaaS Render
├── run.bat                  # Script Windows one-click launcher (Backend + Frontend)
│
├── backend/
│   ├── main.py              # Titik masuk FastAPI, router API, dan static mount
│   ├── run_server.py        # Helper launcher server Uvicorn
│   ├── collector.py         # Skrip pengumpul data POI dari OpenStreetMap
│   ├── overpass.py          # Modul pemanggil Overpass QL API dengan retry/backoff
│   ├── normalizer.py        # Normalisasi tag mentah OSM ke skema canonical
│   ├── activity.py          # Deteksi perubahan objek OSM dan scoring aktivitas
│   ├── mapping.py           # Algoritma pencocokan kandidat perusahaan ke data OSM
│   ├── pdf_ingestion.py     # Pipeline antrian dan pemrosesan dokumen PDF
│   ├── ai_curation.py       # Engine kurasi LLM (OpenAI, Groq, Together, Ollama)
│   ├── preferences.py       # Manajemen konfigurasi dan enkripsi token AI
│   ├── storage.py           # Helper baca/tulis JSON database atomik
│   ├── administrative_reference.py # Referensi sinkronisasi wilayah Indonesia
│   ├── requirements.txt     # Kebutuhan dependensi Python
│   │
│   ├── data/                # Basis data file JSON lokal
│   │   ├── businesses.json  # Data POI bisnis OSM Kota Surakarta
│   │   ├── activities.json  # Log jejak aktivitas data OSM
│   │   ├── metadata.json    # Metadata penarikan data terkini
│   │   ├── pdf_ingestion.json # Status proyek dan registri dokumen PDF
│   │   └── jawa_tengah/     # Mapping regional per kabupaten/kota
│   │       ├── kota_surakarta/
│   │       │   └── business_database_mapping.json
│   │       └── kabupaten_kendal/
│   │           └── business_database_mapping.json
│   │
│   ├── pdf_tools/           # Ekstraktor teks & kandidat perusahaan
│   │   └── extract_company_candidates.py
│   └── scripts/             # Skrip utilitas backend
│
├── frontend/
│   ├── index.html           # File template HTML
│   ├── package.json         # Konfigurasi dependensi Node.js
│   ├── vite.config.ts       # Konfigurasi bundler Vite
│   └── src/
│       ├── main.tsx         # Dashboard utama, peta, filter, dan database view
│       ├── PdfExtractionDashboard.tsx # Studio upload PDF dan editor kandidat
│       ├── SettingsModal.tsx # Dialog pengaturan AI provider dan prompt ruleset
│       └── styles.css       # Design system, CSS variables, dan styling komponen
│
├── configuration/
│   └── ruleset.md           # Aturan default kurasi dan verifikasi data
├── document/                # Direktori sumber dokumen PDF per wilayah
├── output/                  # Direktori artefak hasil parsing (JSON, Markdown, CSV)
└── tests/                   # Kumpulan unit test otomatis
    ├── test_ai_curation.py
    ├── test_company_candidates.py
    ├── test_legal_crawler.py
    └── test_pdf_ingestion_cleanup.py
```

---

## ⚙ Panduan Instalasi & Persiapan

### Prasyarat Sistem
- **Python**: Versi `3.11` atau `3.12`
- **Node.js**: Versi `18.x` atau yang lebih baru (disertai `npm`)
- **Java JRE** *(Opsional)*: Diperlukan jika ingin menggunakan mesin *OpenDataLoader* berbasis Java. Jika hanya menggunakan mesin *PyMuPDF*, Java tidak diperlukan.

### 1. Kloning Repositori
```bash
git clone https://github.com/acttogreen/BusinessCrawlingIntel.git
cd BusinessCrawlingIntel
```

### 2. Konfigurasi Lingkungan Backend (Python)
Buat virtual environment dan pasang dependensi:
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate

# Pasang dependensi
pip install -r backend/requirements.txt
```

### 3. Konfigurasi Frontend (Node.js)
```bash
cd frontend
npm install
cd ..
```

### 4. File Konfigurasi `.env` (Opsional)
Aplikasi mendukung konfigurasi melalui `.env` di *root* direktori. Anda dapat membuat file `.env`:
```env
# URL Basis API untuk Frontend
VITE_API_BASE=http://127.0.0.1:8000

# Path output hasil ekstraksi PDF (opsional, default: output/pdf-parser)
PDF_OUTPUT_ROOT=output/pdf-parser

# Batasan ukuran file PDF dalam bytes (opsional, default: 100MB)
PDF_MAX_BYTES=104857600
```
> **Catatan Token AI**: Token penyedia AI (OpenAI/Groq/dll.) dapat langsung dimasukkan melalui antarmuka menu **Settings (⚙)** di web dashboard dan akan tersimpan terenkripsi secara otomatis.

---

## 🏃 Cara Menjalankan Aplikasi

### Opsi 1: Menjalankan Cepat (Windows)
Cukup jalankan script batch otomatis yang telah disediakan di root:
```cmd
run.bat
```
Script ini akan:
1. Memeriksa ketersediaan virtual environment Python dan `node_modules`.
2. Menghentikan proses lawas yang menduduki port `8000` atau `5173`.
3. Menjalankan server backend FastAPI pada `http://127.0.0.1:8000`.
4. Menjalankan dev server Vite pada `http://localhost:5173`.
5. Membuka browser web Anda secara otomatis.

---

### Opsi 2: Menjalankan Manual di Dua Terminal

#### Terminal 1 — Backend (FastAPI):
```bash
# Pastikan virtual environment aktif
python backend/run_server.py
```
Backend akan aktif di `http://127.0.0.1:8000` (dokumentasi Swagger interaktif dapat diakses di `http://127.0.0.1:8000/docs`).

#### Terminal 2 — Frontend (Vite):
```bash
cd frontend
npm run dev -- --host localhost
```
Frontend akan aktif di `http://localhost:5173`.

---

### Opsi 3: Menjalankan Menggunakan Docker
Aplikasi dilengkapi dengan `Dockerfile` multi-stage:
```bash
# Build image
docker build -t business-crawling-intel .

# Jalankan container
docker run -p 8000:8000 business-crawling-intel
```
Akses aplikasi melalui peramban di `http://localhost:8000`.

---

## 📄 Pipeline Ekstraksi & Kurasi Dokumen (PDF)

Untuk memasukkan direktori bisnis resmi dari dokumen pemerintah:

1. **Buka PDF Extractor**: Di topbar aplikasi, klik tombol **▤ PDF Extractor**.
2. **Buat Proyek**:
   - Pilih **Provinsi** dan **Kabupaten/Kota**.
   - Tentukan **Tahun Sumber** dokumen.
   - Pilih mesin parser: **OpenDataLoader** atau **PyMuPDF**.
3. **Unggah Dokumen**: Unggah satu atau beberapa berkas PDF direktori.
4. **Proses Ekstraksi**: Klik tombol **Proses Dokumen**. Mesin akan mengekstrak teks, tata letak tabel, dan menghasilkan artefak `company_candidates.json` serta `company_candidates.csv`.
5. **Review & Edit Kandidat**: Telusuri daftar kandidat perusahaan yang berhasil dideteksi. Anda dapat mengedit nama, alamat, legalitas, atau menghapus baris tak valid.
6. **Kurasi AI**: Klik **Mulai Kurasi AI** untuk merapikan nama entitas, memvalidasi nomor kontak, dan mengklasifikasikan sektor usaha secara otomatis berdasarkan ruleset.
7. **Sinkronisasi ke OSM**: Klik **Proses Pemetaan OSM** untuk menjalankan algoritma pencocokan dengan basis data geospasial wilayah tersebut.

---

## 🗺 Koleksi Data OpenStreetMap & Pemetaan Entitas

### Menjalankan Koleksi Data OSM Mandiri
Jika ingin mengambil data mutakhir dari Overpass API untuk area tertentu:
```bash
python -m backend.collector --area "Surakarta"
```
Parameter yang tersedia:
- `--area`: Nama wilayah administratif OSM (default: `Surakarta`).
- `--endpoint`: Kustom endpoint Overpass (default: `https://overpass-api.de/api/interpreter`).
- `--timeout`: Waktu tunggu request dalam detik.
- `--retries`: Jumlah percobaan jika terjadi rate-limiting / timeout.

Skrip ini akan mengambil POI, menormalkannya ke skema canonical di `backend/data/businesses.json`, serta mendeteksi pembaruan data dan mencatat perubahannya ke `backend/data/activities.json`.

---

## 🔌 Daftar Endpoint API Utama

| Kategori | Metode | Endpoint | Deskripsi |
| :--- | :--- | :--- | :--- |
| **Bisnis & OSM** | `GET` | `/api/businesses` | Mengambil daftar bisnis dengan multi-filter & pagination |
| | `GET` | `/api/businesses/{id}` | Detail rekod bisnis spesifik |
| | `GET` | `/api/businesses/{id}/activities` | Log histori aktivitas spasial pada objek bisnis |
| | `GET` | `/api/categories` | Daftar sektor dan kategori bisnis |
| | `GET` | `/api/statistics` | Ringkasan metrik total bisnis dan distribusi kategori |
| **Ekspor** | `GET` | `/api/export.csv` | Mengunduh rekod terfilter dalam format CSV (UTF-8 BOM) |
| | `GET` | `/api/export.xlsx` | Mengunduh rekod terfilter dalam format native Microsoft Excel |
| **Administrasi** | `GET` | `/api/data/regions` | Daftar wilayah yang memiliki data pemetaan aktif |
| | `GET` | `/api/administrative/provinces` | Master data provinsi Indonesia |
| | `GET` | `/api/administrative/provinces/{code}/regions` | Master data kabupaten/kota berdasarkan provinsi |
| | `GET` | `/api/regions/{prov}/{reg}/business-database-mapping` | Data gabungan registri dan status pemetaan OSM regional |
| **PDF Ingestion** | `GET` | `/api/ingestion/projects` | Daftar seluruh proyek ingest PDF |
| | `POST` | `/api/ingestion/projects` | Membuat proyek ingest baru |
| | `POST` | `/api/ingestion/projects/{id}/documents` | Mengunggah file PDF ke dalam proyek |
| | `POST` | `/api/ingestion/projects/{id}/process` | Memicu parsing dokumen PDF yang diunggah |
| | `GET` | `/api/ingestion/documents/{id}/companies` | Mengambil daftar entitas bisnis hasil ekstraksi |
| | `PUT` | `/api/ingestion/documents/{id}/companies/{index}` | Mengupdate rekod kandidat bisnis secara langsung |
| | `DELETE` | `/api/ingestion/documents/{id}/companies/{index}` | Menghapus kandidat bisnis dari hasil ekstraksi |
| | `POST` | `/api/ingestion/projects/{id}/process-osm` | Menjalankan pencocokan kandidat PDF ke database OSM |
| **AI Curation** | `GET` | `/api/preferences` | Status dan preferensi penyedia AI saat ini |
| | `POST` | `/api/preferences` | Menyimpan konfigurasi LLM (provider, model, token, dll) |
| | `POST` | `/api/preferences/check-token` | Uji konektivitas dan validitas token AI |
| | `POST` | `/api/ingestion/projects/{id}/curate` | Menjalankan job kurasi AI di latar belakang |
| | `GET` | `/api/ingestion/projects/{id}/curate/{job_id}` | Memeriksa status dan progres job kurasi AI |
| **Sistem** | `GET` | `/health` | Pemeriksaan kesehatan layanan (*health check*) |

---

## 🧪 Pengujian (Testing)

Proyek ini dilengkapi rangkaian unit test otomatis untuk memastikan kestabilan pipeline pemrosesan teks, kurasi LLM, dan operasi file:

```bash
# Menjalankan seluruh pengujian dengan modul unittest bawaan Python
python -m unittest discover tests

# Atau menggunakan pytest jika terpasang
pytest tests/
```

Cakupan pengujian meliputi:
- **`test_ai_curation.py`**: Validasi pemotongan respon LLM, format JSON, aturan kurasi agar tidak menghilangkan kandidat tanpa verifikasi.
- **`test_company_candidates.py`**: Pengujian ekstraksi multi-nomor telepon Indonesia, pembersihan nomor klasifikasi sektor, dan parsing markdown direktori.
- **`test_pdf_ingestion_cleanup.py`**: Pengujian integritas penghapusan proyek dan pembersihan file state.

---

## 🛡 Prinsip Integritas Data (Data Provenance)

Aplikasi ini mematuhi pedoman integritas data yang ketat:
1. **Atribusi Sumber Asli**: Setiap entitas menyimpan referensi dokumen asal (`source`, `source_url`, `evidence`) dan/atau referensi OSM (`osm_type`, `osm_id`).
2. **Tidak Ada Rekayasa Status Hukum**: Keberadaan sebuah entitas di OpenStreetMap tidak serta merta membuktikan bahwa entitas tersebut memiliki badan hukum resmi atau izin operasional aktif.
3. **Penyimpanan Lokal & Privasi**: Dokumen yang diunggah dan kunci rahasia API tersimpan di direktori lokal pengguna, tidak dikirim ke server analitik pihak ketiga yang tidak berwenang.

---

## 👨‍💻 Kontributor & Lisensi

- **Pengembang Utama**: [acttogreen_rbs](https://github.com/acttogreen)
- **Lisensi**: Proyek ini dilisensikan di bawah ketentuan lisensi internal / proyek terbuka. Silakan merujuk pada berkas konfigurasi repositori untuk rincian lebih lanjut.
- **Data Geospasial**: © [OpenStreetMap](https://www.openstreetmap.org/copyright) kontributor (ODbL).
