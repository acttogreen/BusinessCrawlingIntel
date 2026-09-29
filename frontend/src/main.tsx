import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as maplibregl from "maplibre-gl";
import type { Map, Marker } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import "./styles.css";

type Language = "id" | "en";
type Business = {
  id: string; name: string; category: string; subcategory: string;
  business_type?: string; established_year?: number | null;
  location: { latitude: number; longitude: number }; address: Record<string, string | undefined>;
  contact: { phone?: string | null; website?: string | null; email?: string | null };
  source?: string;
  legal?: { status?: string; entity_name?: string; entity_type?: string; checked_at?: string; evidence?: { url?: string; observed_at?: string }[] };
  active?: boolean; activity?: { last_event_at?: string; last_event_type?: string; score?: number };
  metadata: { osm_type?: string; osm_id?: number; last_seen_at?: string; osm_tags?: Record<string, string> };
  registry?: { legal_entity?: string; investment_type?: string; business_sector?: string; district?: string; source_url?: string; evidence?: string };
  investment?: { status?: string; type?: string }; mapping?: { status?: string; confidence?: number; match_method?: string };
};
type ActivityEvent = { business_id?: string; type: string; detected_at: string; description: string; details?: Record<string, unknown> };
type DatabaseSortKey = "id" | "name" | "category" | "business_type" | "legal_entity" | "investment_type" | "contact" | "year" | "coordinates" | "source";

const countValues = (businesses: Business[], getValue: (business: Business) => string | undefined) => Object.entries(businesses.reduce<Record<string, number>>((counts, business) => { const value = getValue(business) || "Unknown"; counts[value] = (counts[value] || 0) + 1; return counts; }, {})).sort((a, b) => b[1] - a[1]);

function AnalyticsModal({ businesses, language, onClose }: { businesses: Business[]; language: Language; onClose: () => void }) {
  const legal = countValues(businesses, (business) => business.registry?.legal_entity);
  const investment = countValues(businesses, (business) => business.registry?.investment_type);
  const sectors = countValues(businesses, (business) => business.registry?.business_sector);
  const districts = countValues(businesses, (business) => business.registry?.district);
  const pieTotal = legal.reduce((sum, [, value]) => sum + value, 0) || 1;
  let offset = 0;
  const pie = legal.map(([label, value], index) => { const start = offset; offset += (value / pieTotal) * 100; return `${["#e76f51", "#2a9d8f", "#457b9d", "#e9c46a", "#8d6e9f", "#6b8f71"][index % 6]} ${start}% ${offset}%`; });
  const chart = (title: string, entries: [string, number][]) => <div className="analytics-chart"><h3>{title}</h3><div className="bar-chart" role="img" aria-label={title}>{entries.slice(0, 8).map(([label, value]) => <div className="bar-row" key={label}><span className="bar-label" title={label}>{label}</span><span className="bar-track"><span className="bar-fill" style={{ width: `${(value / Math.max(entries[0]?.[1] || 1, 1)) * 100}%` }} /></span><strong>{value}</strong></div>)}</div></div>;
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className="analytics-modal" role="dialog" aria-modal="true" aria-labelledby="analytics-title"><div className="modal-header"><div><p className="eyebrow">{language === "id" ? "DEMOGRAFI PERUSAHAAN" : "COMPANY DEMOGRAPHICS"}</p><h2 id="analytics-title">{language === "id" ? "Analitik bisnis Surakarta" : "Surakarta business analytics"}</h2><p className="modal-description">{businesses.length.toLocaleString()} {language === "id" ? "record database terbaru" : "records from the latest database"}</p></div><button className="close" onClick={onClose} aria-label={language === "id" ? "Tutup" : "Close"}>×</button></div><div className="analytics-content"><div className="analytics-grid">{chart(language === "id" ? "Distribusi sektor usaha" : "Business sector distribution", sectors)}{chart(language === "id" ? "Distribusi kecamatan" : "District distribution", districts)}<div className="analytics-chart pie-chart-panel"><h3>{language === "id" ? "Komposisi badan hukum" : "Legal entity composition"}</h3><div className="pie-chart" role="img" aria-label={language === "id" ? "Pie chart badan hukum" : "Legal entity pie chart"} style={{ background: `conic-gradient(${pie.join(", ")})` }} /><div className="pie-legend">{legal.slice(0, 8).map(([label, value], index) => <span key={label}><i style={{ background: ["#e76f51", "#2a9d8f", "#457b9d", "#e9c46a", "#8d6e9f", "#6b8f71"][index % 6] }} />{label} {value}</span>)}</div></div>{chart(language === "id" ? "Jenis investasi" : "Investment type", investment)}</div></div></section></div>;
}

const DATA_BASE = `${import.meta.env.BASE_URL}data`;
const categoryNames: Record<string, { id: string; en: string }> = {
  all: { id: "Semua kategori", en: "All categories" },
  food_and_services: { id: "Makanan dan layanan", en: "Food and services" },
  accommodation_and_tourism: { id: "Akomodasi dan wisata", en: "Accommodation and tourism" },
  retail: { id: "Ritel", en: "Retail" },
  professional_services: { id: "Jasa profesional", en: "Professional services" },
  leisure_and_sports: { id: "Rekreasi dan olahraga", en: "Leisure and sports" },
  craft_and_manufacturing: { id: "Kerajinan dan manufaktur", en: "Craft and manufacturing" },
};
const copy: Record<Language, Record<string, string>> = {
  id: { title: "Intelijen bisnis", source: "Database bisnis + OSM", mapped: "Bisnis database", visible: "Terlihat sekarang", explore: "Jelajahi", categories: "sektor", category: "Sektor", places: "Bisnis", database: "Database", databaseTitle: "Isi database", databaseDescription: "Database bisnis resmi dengan pengayaan lokasi OpenStreetMap", search: "Cari nama atau ID...", showing: "Menampilkan", of: "dari", previous: "Sebelumnya", next: "Berikutnya", address: "Alamat", phone: "Telepon", website: "Situs web", sourceLabel: "Sumber", close: "Tutup", noResults: "Tidak ada record yang cocok.", language: "Bahasa", theme: "Tema", light: "Terang", dark: "Gelap", coordinates: "Koordinat", idLabel: "ID", name: "Nama", year: "Tahun berdiri", businessType: "Sektor usaha", activity: "Aktivitas data", recentActivity: "Perubahan terakhir", activityAll: "Semua aktivitas", activity7: "7 hari", activity30: "30 hari", activity90: "90 hari", activity365: "1 tahun", activityUnknown: "Belum ada event", score: "Skor perubahan", timeline: "Timeline perubahan", created: "Dibuat", updated: "Diperbarui", removed: "Belum terpetakan", addCategory: "Tambah kategori", categoryName: "Nama kategori baru", save: "Simpan", updateFailed: "Gagal memperbarui record.", view: "Lihat", edit: "Edit", exportCsv: "CSV", exportExcel: "Excel", refresh: "Refresh OSM", refreshQueued: "Menunggu...", refreshRunning: "Memperbarui OSM...", refreshCompleted: "Data OSM diperbarui", refreshFailed: "Refresh gagal", legalDetails: "Informasi legal", legalStatus: "Badan hukum", legalName: "Nama badan usaha", legalUnknown: "Belum ditemukan", legalUnverified: "Petunjuk, belum terverifikasi", legalVerified: "Terverifikasi", legalSource: "Bukti sumber", investmentType: "Jenis investasi", contact: "Kontak", changelog: "Changelog", analytics: "Analitik", version: "Versi", legalEntity: "Bentuk badan hukum", mappingStatus: "Status OSM", mappedStatus: "Terpetakan", unmatchedStatus: "Belum terpetakan" },
  en: { title: "Business intelligence", source: "Business database + OSM", mapped: "Database businesses", visible: "Visible now", explore: "Explore", categories: "sectors", category: "Sector", places: "Businesses", database: "Database", databaseTitle: "Database contents", databaseDescription: "Official business database enriched with OpenStreetMap locations", search: "Search name or ID...", showing: "Showing", of: "of", previous: "Previous", next: "Next", address: "Address", phone: "Phone", website: "Website", sourceLabel: "Source", close: "Close", noResults: "No matching records.", language: "Language", theme: "Theme", light: "Light", dark: "Dark", coordinates: "Coordinates", idLabel: "ID", name: "Name", year: "Established year", businessType: "Business sector", activity: "Data activity", recentActivity: "Recent change", activityAll: "All activity", activity7: "7 days", activity30: "30 days", activity90: "90 days", activity365: "1 year", activityUnknown: "No event yet", score: "Change score", timeline: "Change timeline", created: "Created", updated: "Updated", removed: "Not mapped", addCategory: "Add category", categoryName: "New category name", save: "Save", updateFailed: "Could not update record.", view: "View", edit: "Edit", exportCsv: "CSV", exportExcel: "Excel", refresh: "Refresh OSM", refreshQueued: "Queued...", refreshRunning: "Refreshing OSM...", refreshCompleted: "OSM data updated", refreshFailed: "Refresh failed", legalDetails: "Legal information", legalStatus: "Legal entity", legalName: "Legal entity name", legalUnknown: "Not found", legalUnverified: "Clue, unverified", legalVerified: "Verified", legalSource: "Source evidence", investmentType: "Investment type", contact: "Contact", changelog: "Changelog", analytics: "Analitik", version: "Version", legalEntity: "Legal entity", mappingStatus: "OSM status", mappedStatus: "Mapped", unmatchedStatus: "Not mapped" },
};
const prettyLabel = (value: string) => value.replace(/_/g, " ").replace(/\b\w/g, (char: string) => char.toUpperCase());
const categoryLabel = (value: string, language: Language) => categoryNames[value]?.[language] ?? prettyLabel(value);

function App() {
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [category, setCategory] = useState("all");
  const [businessType, setBusinessType] = useState("all");
  const [establishedYear, setEstablishedYear] = useState("all");
  const [activityDays, setActivityDays] = useState("all");
  const [investmentType, setInvestmentType] = useState("all");
  const [legalEntity, setLegalEntity] = useState("all");
  const [mappingStatus, setMappingStatus] = useState("all");
  const [placesPage, setPlacesPage] = useState(0);
  const [activityEvents, setActivityEvents] = useState<ActivityEvent[]>([]);
  const [categoryOptions, setCategoryOptions] = useState<{ id: string; name: string }[]>([]);
  const [selected, setSelected] = useState<Business | null>(null);
  const [error, setError] = useState("");
  const [language, setLanguage] = useState<Language>(() => (localStorage.getItem("sbi-language") as Language) || "id");
  const [darkMode, setDarkMode] = useState(() => localStorage.getItem("sbi-theme") === "dark");
  const [databaseOpen, setDatabaseOpen] = useState(false);
  const [databaseTab, setDatabaseTab] = useState<"view" | "edit">("view");
  const [databaseQuery, setDatabaseQuery] = useState("");
  const [databaseCategory, setDatabaseCategory] = useState("all");
  const [databasePage, setDatabasePage] = useState(0);
  const [databaseSort, setDatabaseSort] = useState<{ key: DatabaseSortKey; direction: "asc" | "desc" }>({ key: "name", direction: "asc" });
  const [changelogOpen, setChangelogOpen] = useState(false);
  const [analyticsOpen, setAnalyticsOpen] = useState(false);
  const [newCategory, setNewCategory] = useState("");
  const [categoryStatus, setCategoryStatus] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState("");
  const mapNode = useRef<HTMLDivElement>(null);
  const map = useRef<Map | null>(null);
  const markers = useRef<Marker[]>([]);
  const activityData = useRef<ActivityEvent[]>([]);
  const t: Record<string, string> = { all: language === "id" ? "Semua" : "All", unknownYear: language === "id" ? "Tahun tidak diketahui" : "Unknown year", ...copy[language] };

  useEffect(() => {
    Promise.all([fetch(`${DATA_BASE}/business_database_mapping.json`), fetch(`${DATA_BASE}/activities.json`)]).then(async ([businessResponse, activityResponse]) => {
      const [mappingData, activityData] = await Promise.all([businessResponse.json(), activityResponse.json()]);
      const businessData = mappingData.businesses.map((item: any): Business => ({ id: item.id, name: item.name, category: item.registry.business_sector || "unknown", subcategory: item.registry.business_sector || "unknown", business_type: item.registry.business_sector || "unknown", established_year: null, location: item.osm.location || { latitude: 0, longitude: 0 }, address: { "addr:suburb": item.registry.district, "addr:city": item.registry.city, display: item.registry.address }, contact: { phone: item.registry.phone || item.registry.phone_number, email: item.registry.email, website: item.registry.website }, source: "Business_database_5.0", legal: { status: "known", entity_type: item.registry.legal_entity }, investment: { status: "known", type: item.registry.investment_type }, activity: {}, metadata: { osm_type: item.osm.osm_type, osm_id: item.osm.osm_id, osm_tags: item.osm.tags }, active: item.osm.status === "matched", registry: item.registry, mapping: { status: item.osm.status, confidence: item.osm.confidence, match_method: item.osm.match_method } }));
      const overrides = JSON.parse(localStorage.getItem("sbi-category-overrides") || "{}");
      setBusinesses(businessData.map((business: Business) => overrides[business.id] ? { ...business, category: overrides[business.id] } : business));
      activityData.current = activityData;
      setActivityEvents([]);
      const custom = JSON.parse(localStorage.getItem("sbi-custom-categories") || "[]");
      const builtIn = Object.entries(categoryNames).filter(([id]) => id !== "all").map(([id, names]) => ({ id, name: names[language] }));
      setCategoryOptions([...builtIn, ...custom.filter((item: { id: string }) => !builtIn.some((option) => option.id === item.id))]);
    }).catch(() => setError(language === "id" ? "Dataset statis tidak dapat dimuat." : "Could not load the static dataset."));
  }, [language]);
  useEffect(() => { localStorage.setItem("sbi-language", language); }, [language]);
  useEffect(() => { localStorage.setItem("sbi-theme", darkMode ? "dark" : "light"); }, [darkMode]);

  const categories = useMemo(() => ["all", ...Array.from(new Set([...businesses.map((business) => business.category), ...categoryOptions.map((item) => item.id)])).sort()], [businesses, categoryOptions]);
  const businessTypes = useMemo(() => ["all", ...Array.from(new Set(businesses.map((business) => business.business_type || business.subcategory))).filter(Boolean).sort()], [businesses]);
  const establishedYears = useMemo(() => ["all", ...Array.from(new Set(businesses.map((business) => business.established_year).filter((year): year is number => typeof year === "number"))).sort((a, b) => b - a).map(String)], [businesses]);
  const investmentTypes = useMemo(() => ["all", ...Array.from(new Set(businesses.map((business) => business.investment?.type).filter(Boolean) as string[])).sort()], [businesses]);
  const legalEntities = useMemo(() => ["all", ...Array.from(new Set(businesses.map((business) => business.legal?.entity_type).filter(Boolean) as string[])).sort()], [businesses]);
  const databaseSectors = useMemo(() => ["all", ...Array.from(new Set(businesses.map((business) => business.category).filter(Boolean))).sort()], [businesses]);
  const filtered = useMemo(() => businesses.filter((business) => {
    const recent = activityDays === "all" || (activityDays === "unknown" ? !business.activity?.last_event_at : Boolean(business.activity?.last_event_at && Date.now() - Date.parse(business.activity.last_event_at) <= Number(activityDays) * 86400000));
    return (category === "all" || business.category === category) && (businessType === "all" || (business.business_type || business.subcategory) === businessType) && (investmentType === "all" || business.investment?.type === investmentType) && (legalEntity === "all" || business.legal?.entity_type === legalEntity) && (mappingStatus === "all" || business.mapping?.status === mappingStatus) && (establishedYear === "all" || (establishedYear === "unknown" ? !business.established_year : String(business.established_year) === establishedYear)) && recent;
  }), [businesses, category, businessType, investmentType, legalEntity, mappingStatus, establishedYear, activityDays]);
  const placesPageSize = 50;
  const placesPageCount = Math.max(1, Math.ceil(filtered.length / placesPageSize));
  const placesPageIndex = Math.min(placesPage, placesPageCount - 1);
  const placesPageRows = filtered.slice(placesPageIndex * placesPageSize, (placesPageIndex + 1) * placesPageSize);
  const databaseRows = useMemo(() => {
    const query = databaseQuery.trim().toLowerCase();
    const rows = businesses.filter((business) => (databaseCategory === "all" || business.category === databaseCategory) && (!query || business.name.toLowerCase().includes(query) || business.id.toLowerCase().includes(query)));
    const value = (business: Business): string | number => ({ id: business.id, name: business.name, category: business.category, business_type: business.business_type || business.subcategory, legal_entity: business.registry?.legal_entity || "", investment_type: business.registry?.investment_type || "", contact: business.contact?.phone || business.contact?.email || business.contact?.website || "", year: business.established_year || 0, coordinates: business.mapping?.status === "matched" ? `${business.location.latitude},${business.location.longitude}` : "", source: business.mapping?.status === "matched" ? `OSM ${business.metadata.osm_type} ${business.metadata.osm_id}` : "Business database" }[databaseSort.key]);
    return rows.sort((a, b) => { const left = value(a); const right = value(b); const result = typeof left === "number" && typeof right === "number" ? left - right : String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" }); return databaseSort.direction === "asc" ? result : -result; });
  }, [businesses, databaseQuery, databaseCategory, databaseSort]);
  const pageSize = 50;
  const pageCount = Math.max(1, Math.ceil(databaseRows.length / pageSize));
  const pageRows = databaseRows.slice(databasePage * pageSize, (databasePage + 1) * pageSize);
  const selectedActivityEvents = useMemo(() => activityEvents.filter((event) => event.business_id === selected?.id), [activityEvents, selected]);
  const toggleDatabaseSort = (key: DatabaseSortKey) => setDatabaseSort((current) => current.key === key ? { key, direction: current.direction === "asc" ? "desc" : "asc" } : { key, direction: "asc" });
  const sortIndicator = (key: DatabaseSortKey) => databaseSort.key === key ? (databaseSort.direction === "asc" ? "↑" : "↓") : "↕";
  const changelogItems = language === "id" ? ["Business_database_5.0 menjadi sumber utama dengan 863 record.", "OSM mapping diperbarui: 52 bisnis terpetakan.", "Filter legal entity dan investment type diperbarui.", "Dropdown sektor JSON Database kini mengikuti business_sector terbaru.", "Kolom database dapat di-sort saat header diklik dan di-resize.", "Kontak bisnis ditambahkan ke JSON Database View.", "Window Analitik ditambahkan dengan grafik sektor, kecamatan, badan hukum, dan investasi.", "Pie chart komposisi badan hukum ditambahkan untuk analisis demografis Surakarta.", "Changelog kini mengikuti toggle bahasa ID/EN.", "Credit developer dan tech stack ditambahkan."] : ["Business_database_5.0 is now the primary source with 863 records.", "OSM mapping updated: 52 businesses mapped.", "Legal entity and investment type filters updated.", "The JSON Database sector dropdown now follows the latest business_sector values.", "Database columns now support click-to-sort and resizing.", "Business contact details added to JSON Database View.", "An Analytics window was added with sector, district, legal entity, and investment charts.", "A legal entity composition pie chart was added for Surakarta demographic analysis.", "Changelog now follows the ID/EN language toggle.", "Developer credit and tech stack information added."];

  useEffect(() => { setDatabasePage(0); }, [databaseQuery, databaseCategory, databaseTab]);
  useEffect(() => { setPlacesPage(0); }, [category, businessType, investmentType, legalEntity, mappingStatus, establishedYear, activityDays]);
  useEffect(() => {
    if (!mapNode.current || map.current) return;
    maplibregl.setWorkerUrl(new URL("maplibre-gl/dist/maplibre-gl-worker.mjs", import.meta.url).toString());
    const instance = new maplibregl.Map({ container: mapNode.current, center: [110.825, -7.57], zoom: 12, style: { version: 8, sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap contributors" } }, layers: [{ id: "osm", type: "raster", source: "osm" }] } });
    map.current = instance;
    instance.addControl(new maplibregl.NavigationControl(), "top-right");
    return () => { map.current?.remove(); map.current = null; };
  }, []);
  useEffect(() => {
    if (!map.current) return;
    markers.current.forEach((marker) => marker.remove());
    markers.current = filtered.map((business) => {
      if (business.mapping?.status !== "matched") return null;
      const marker = new maplibregl.Marker({ color: "#e76f51" }).setLngLat([business.location.longitude, business.location.latitude]).addTo(map.current!);
      marker.getElement().addEventListener("click", () => setSelected(business));
      return marker;
    }).filter(Boolean) as Marker[];
  }, [filtered]);

  const displayCategory = (value: string) => categoryOptions.find((item) => item.id === value)?.name || categoryLabel(value, language);
  const selectBusiness = (business: Business) => { setSelected(business); setActivityEvents(activityData.current.filter((event) => event.business_id === business.id)); setDatabaseOpen(false); if (business.mapping?.status === "matched") map.current?.flyTo({ center: [business.location.longitude, business.location.latitude], zoom: 16 }); };
  const addCategory = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!newCategory.trim()) return;
    const id = newCategory.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "new_category";
    if (categoryOptions.some((item) => item.id === id) || categories.includes(id)) { setCategoryStatus(language === "id" ? "Kategori sudah ada atau tidak valid." : "Category already exists or is invalid."); return; }
    const created = { id, name: newCategory.trim() };
    const updated = [...categoryOptions, created];
    setCategoryOptions(updated); localStorage.setItem("sbi-custom-categories", JSON.stringify(updated)); setNewCategory(""); setCategoryStatus(created.name);
  };
  const updateBusinessCategory = (businessId: string, value: string) => {
    setBusinesses((current) => current.map((business) => business.id === businessId ? { ...business, category: value } : business));
    setCategoryStatus(language === "id" ? "Record diperbarui di browser." : "Record updated in this browser.");
    const overrides = JSON.parse(localStorage.getItem("sbi-category-overrides") || "{}");
    overrides[businessId] = value; localStorage.setItem("sbi-category-overrides", JSON.stringify(overrides));
  };
  const exportHref = (format: "csv" | "xlsx") => {
    const rows = databaseRows.map((business) => [business.id, business.name, business.category, business.business_type || business.subcategory, business.established_year || "", business.location.latitude, business.location.longitude, business.contact.phone || "", business.contact.website || "", business.source || "openstreetmap"]);
    const headers = ["ID", "Name", "Category", "Business Type", "Established Year", "Latitude", "Longitude", "Phone", "Website", "Source"];
    if (format === "csv") {
      const csv = [headers, ...rows].map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(",")).join("\n");
      return `data:text/csv;charset=utf-8,%EF%BB%BF${encodeURIComponent(csv)}`;
    }
    const xmlRows = [headers, ...rows].map((row) => `<Row>${row.map((value) => `<Cell><Data ss:Type="String">${String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</Data></Cell>`).join("")}</Row>`).join("");
    return `data:application/vnd.ms-excel;charset=utf-8,${encodeURIComponent(`<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="Businesses"><Table>${xmlRows}</Table></Worksheet></Workbook>`)}`;
  };
  const refreshOsm = async () => {
    if (refreshing) return;
    setRefreshing(true);
    setRefreshMessage(language === "id" ? "Mode statis: crawl lokal lalu deploy ulang." : "Static mode: crawl locally, then redeploy.");
    window.setTimeout(() => { setRefreshing(false); setRefreshMessage(""); }, 3500);
  };

  return <div className={`app-shell ${darkMode ? "theme-dark" : ""}`}>
    <header className="topbar"><div><p className="eyebrow">KOTA SURAKARTA</p><h1>{t.title}</h1></div><nav className="top-actions" aria-label="Dashboard controls"><button className="refresh-button" onClick={refreshOsm} disabled={refreshing}>↻ <span>{refreshing ? refreshMessage : t.refresh}</span></button><button className="database-button" onClick={() => setDatabaseOpen(true)}>▦ <span>{t.database}</span></button><button className="database-button" onClick={() => setChangelogOpen(true)}>⌘ <span>{t.changelog}</span></button><button className="database-button" onClick={() => setAnalyticsOpen(true)}>▥ <span>{t.analytics}</span></button><button className="language-toggle" onClick={() => setLanguage(language === "id" ? "en" : "id")} aria-label={`${t.language}: ${language.toUpperCase()}`}>{language === "id" ? "ID" : "EN"}</button><button className="theme-toggle" onClick={() => setDarkMode(!darkMode)} aria-label={`${t.theme}: ${darkMode ? t.dark : t.light}`}>{darkMode ? "☀" : "☾"}</button><div className="source-badge"><span className="status-dot" /> {t.source}</div></nav></header>
    <main className="dashboard">
      <aside className="sidebar">
        <section className="summary"><div><span className="metric-label">{t.mapped}</span><strong>{businesses.length.toLocaleString()}</strong></div><div><span className="metric-label">{t.visible}</span><strong>{filtered.length.toLocaleString()}</strong></div></section>
        <section className="filters"><div className="section-heading"><h2>{t.explore}</h2><span>{categories.length - 1} {t.categories}</span></div><label htmlFor="category">{t.category}</label><select id="category" value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map((item) => <option key={item} value={item}>{item === "all" ? categoryLabel(item, language) : displayCategory(item)}</option>)}</select><label htmlFor="business-type">{t.businessType}</label><select id="business-type" value={businessType} onChange={(event) => setBusinessType(event.target.value)}>{businessTypes.map((item) => <option key={item} value={item}>{item === "all" ? t.all : prettyLabel(item)}</option>)}</select><label htmlFor="investment-type">{t.investmentType}</label><select id="investment-type" value={investmentType} onChange={(event) => setInvestmentType(event.target.value)}>{investmentTypes.map((item) => <option key={item} value={item}>{item === "all" ? t.all : item}</option>)}</select><label htmlFor="legal-entity">{t.legalEntity}</label><select id="legal-entity" value={legalEntity} onChange={(event) => setLegalEntity(event.target.value)}>{legalEntities.map((item) => <option key={item} value={item}>{item === "all" ? t.all : item}</option>)}</select><label htmlFor="mapping-status">{t.mappingStatus}</label><select id="mapping-status" value={mappingStatus} onChange={(event) => setMappingStatus(event.target.value)}><option value="all">{t.all}</option><option value="matched">{t.mappedStatus}</option><option value="unmatched">{t.unmatchedStatus}</option></select><label htmlFor="established-year">{t.year}</label><select id="established-year" value={establishedYear} onChange={(event) => setEstablishedYear(event.target.value)}><option value="all">{t.all}</option>{establishedYears.slice(1).map((year) => <option key={year} value={year}>{year}</option>)}<option value="unknown">{t.unknownYear}</option></select><label htmlFor="activity-days">{t.recentActivity}</label><select id="activity-days" value={activityDays} onChange={(event) => setActivityDays(event.target.value)}><option value="all">{t.activityAll}</option><option value="7">{t.activity7}</option><option value="30">{t.activity30}</option><option value="90">{t.activity90}</option><option value="365">{t.activity365}</option><option value="unknown">{t.activityUnknown}</option></select></section>
        <section className="business-list"><div className="section-heading"><h2>{t.places}</h2><span>{filtered.length}</span></div>{error && <p className="error">{error}</p>}{placesPageRows.map((business) => <button className={`business-row ${selected?.id === business.id ? "selected" : ""}`} key={business.id} onClick={() => selectBusiness(business)}><span className="pin-dot" /><span><strong>{business.name}</strong><small>{categoryLabel(business.category, language)} · {prettyLabel(business.subcategory)}</small></span></button>)}<div className="places-pagination"><span>{filtered.length ? `${t.showing} ${placesPageIndex * placesPageSize + 1}-${Math.min((placesPageIndex + 1) * placesPageSize, filtered.length)} ${t.of} ${filtered.length}` : t.noResults}</span><div><button onClick={() => setPlacesPage((page) => Math.max(0, page - 1))} disabled={placesPageIndex === 0}>{t.previous}</button><span>{placesPageIndex + 1} / {placesPageCount}</span><button onClick={() => setPlacesPage((page) => Math.min(placesPageCount - 1, page + 1))} disabled={placesPageIndex >= placesPageCount - 1}>{t.next}</button></div></div></section>
      </aside>
        <section className="map-stage"><div ref={mapNode} className="map" />{selected && <article className="detail-panel"><button className="close" onClick={() => setSelected(null)} aria-label={t.close}>×</button><p className="eyebrow">{categoryLabel(selected.category, language)}</p><h2>{selected.name}</h2><p className="detail-subtitle">{prettyLabel(selected.subcategory)}</p><div className="detail-lines">{selected.address.display && <p><span>{t.address}</span>{selected.address.display}</p>}<p><span>{t.legalEntity}</span>{selected.registry?.legal_entity || t.legalUnknown}</p><p><span>{t.investmentType}</span>{selected.registry?.investment_type || t.legalUnknown}</p><p><span>{t.mappingStatus}</span>{selected.mapping?.status === "matched" ? `${t.mappedStatus} (${selected.mapping.confidence})` : t.unmatchedStatus}</p>{selected.registry?.source_url && <p><span>{t.legalSource}</span><a href={selected.registry.source_url} target="_blank" rel="noreferrer">{new URL(selected.registry.source_url).hostname}</a></p>}<p><span>{t.sourceLabel}</span>{selected.mapping?.status === "matched" ? `OpenStreetMap · ${selected.metadata.osm_type} ${selected.metadata.osm_id}` : "business_database3.0"}</p></div></article>}</section>
    </main>
    {analyticsOpen && <AnalyticsModal businesses={businesses} language={language} onClose={() => setAnalyticsOpen(false)} />}{changelogOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setChangelogOpen(false); }}><section className="changelog-modal" role="dialog" aria-modal="true" aria-labelledby="changelog-title"><button className="close" onClick={() => setChangelogOpen(false)} aria-label={t.close}>×</button><p className="eyebrow">{t.changelog}</p><h2 id="changelog-title">{t.version} 5.1.0</h2><p className="changelog-date">29 September 2026</p><ul>{changelogItems.map((item) => <li key={item}>{item}</li>)}</ul><div className="credits"><p><strong>{language === "id" ? "Pengembang" : "Developer"}:</strong> acttogreen_rbs</p><p><strong>{language === "id" ? "Tech stack" : "Tech stack"}:</strong> React, TypeScript, Vite, FastAPI, MapLibre GL JS, OpenStreetMap</p></div></section></div>}{databaseOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDatabaseOpen(false); }}><section className="database-modal" role="dialog" aria-modal="true" aria-labelledby="database-title"><div className="modal-header"><div><p className="eyebrow">JSON DATABASE</p><h2 id="database-title">{t.databaseTitle}</h2><p className="modal-description">{t.databaseDescription}</p></div><button className="close" onClick={() => setDatabaseOpen(false)} aria-label={t.close}>×</button></div><div className="database-tabs" role="tablist"><button className={databaseTab === "view" ? "active" : ""} onClick={() => setDatabaseTab("view")} role="tab" aria-selected={databaseTab === "view"}>{t.view}</button><button className={databaseTab === "edit" ? "active" : ""} onClick={() => setDatabaseTab("edit")} role="tab" aria-selected={databaseTab === "edit"}>{t.edit}</button></div>{databaseTab === "edit" ? <form className="category-form" onSubmit={addCategory}><input value={newCategory} onChange={(event) => setNewCategory(event.target.value)} placeholder={t.categoryName} aria-label={t.categoryName} /><button type="submit">+ {t.addCategory}</button>{categoryStatus && <span>{categoryStatus}</span>}</form> : <div className="database-view-filter"><label htmlFor="database-category-filter">{t.category}</label><select id="database-category-filter" value={databaseCategory} onChange={(event) => setDatabaseCategory(event.target.value)}><option value="all">{t.all}</option>{databaseSectors.slice(1).map((item) => <option key={item} value={item}>{item}</option>)}</select></div>}<div className="database-toolbar"><input className="database-search" value={databaseQuery} onChange={(event) => setDatabaseQuery(event.target.value)} placeholder={t.search} aria-label={t.search} /><div className="export-actions"><a href={exportHref("csv")} download>{t.exportCsv}</a><a href={exportHref("xlsx")} download>{t.exportExcel}</a></div></div><div className="database-table-wrap"><table><thead><tr><th><button className="column-sort" onClick={() => toggleDatabaseSort("id")}>{t.idLabel} {sortIndicator("id")}</button></th><th><button className="column-sort" onClick={() => toggleDatabaseSort("name")}>{t.name} {sortIndicator("name")}</button></th><th><button className="column-sort" onClick={() => toggleDatabaseSort("category")}>{t.category} {sortIndicator("category")}</button></th><th><button className="column-sort" onClick={() => toggleDatabaseSort("business_type")}>{t.businessType} {sortIndicator("business_type")}</button></th><th><button className="column-sort" onClick={() => toggleDatabaseSort("legal_entity")}>{t.legalEntity} {sortIndicator("legal_entity")}</button></th><th><button className="column-sort" onClick={() => toggleDatabaseSort("investment_type")}>{t.investmentType} {sortIndicator("investment_type")}</button></th><th><button className="column-sort" onClick={() => toggleDatabaseSort("contact")}>{t.contact} {sortIndicator("contact")}</button></th><th><button className="column-sort" onClick={() => toggleDatabaseSort("year")}>{t.year} {sortIndicator("year")}</button></th><th><button className="column-sort" onClick={() => toggleDatabaseSort("coordinates")}>{t.coordinates} {sortIndicator("coordinates")}</button></th><th><button className="column-sort" onClick={() => toggleDatabaseSort("source")}>{t.sourceLabel} {sortIndicator("source")}</button></th></tr></thead><tbody>{pageRows.map((business) => <tr key={business.id} onClick={() => selectBusiness(business)}><td className="mono">{business.id}</td><td><strong>{business.name}</strong><small>{prettyLabel(business.subcategory)}</small></td><td onClick={(event) => event.stopPropagation()}>{databaseTab === "edit" ? <select className="database-category" value={business.category} onChange={(event) => updateBusinessCategory(business.id, event.target.value)}>{categoryOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select> : displayCategory(business.category)}</td><td>{prettyLabel(business.business_type || business.subcategory)}</td><td>{business.registry?.legal_entity || "-"}</td><td>{business.registry?.investment_type || "-"}</td><td className="database-contact">{business.contact?.phone || business.contact?.email || business.contact?.website || "-"}</td><td>{business.established_year || "-"}</td><td className="mono">{business.mapping?.status === "matched" ? `${business.location.latitude.toFixed(4)}, ${business.location.longitude.toFixed(4)}` : "-"}</td><td>{business.mapping?.status === "matched" ? `OSM ${business.metadata.osm_type} ${business.metadata.osm_id}` : "Business database"}</td></tr>)}</tbody></table>{pageRows.length === 0 && <p className="empty-state">{t.noResults}</p>}</div><div className="modal-footer"><span>{t.showing} {databaseRows.length === 0 ? 0 : databasePage * pageSize + 1}-{Math.min((databasePage + 1) * pageSize, databaseRows.length)} {t.of} {databaseRows.length}</span><div><button onClick={() => setDatabasePage(Math.max(0, databasePage - 1))} disabled={databasePage === 0}>‹ {t.previous}</button><span className="page-number">{databasePage + 1} / {pageCount}</span><button onClick={() => setDatabasePage(Math.min(pageCount - 1, databasePage + 1))} disabled={databasePage >= pageCount - 1}>{t.next} ›</button></div></div></section></div>}
  </div>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);








