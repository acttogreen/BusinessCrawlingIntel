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
  location: { latitude: number; longitude: number }; address: Record<string, string>;
  contact: { phone?: string | null; website?: string | null; email?: string | null };
  legal?: { status?: string; entity_name?: string; entity_type?: string; checked_at?: string; evidence?: { url?: string; observed_at?: string }[] };
  active?: boolean; activity?: { last_event_at?: string; last_event_type?: string; score?: number };
  metadata: { osm_type?: string; osm_id?: number; last_seen_at?: string; osm_tags?: Record<string, string> };
};
type ActivityEvent = { type: string; detected_at: string; description: string; details?: Record<string, unknown> };

const API = "http://localhost:8000/api";
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
  id: { title: "Intelijen bisnis", source: "Dataset OSM langsung", mapped: "Bisnis terpetakan", visible: "Terlihat sekarang", explore: "Jelajahi", categories: "kategori", category: "Kategori", places: "Tempat", database: "Database", databaseTitle: "Isi database", databaseDescription: "Record bisnis tersimpan dari OpenStreetMap", search: "Cari nama atau ID...", showing: "Menampilkan", of: "dari", previous: "Sebelumnya", next: "Berikutnya", address: "Alamat", phone: "Telepon", website: "Situs web", sourceLabel: "Sumber", close: "Tutup", noResults: "Tidak ada record yang cocok.", language: "Bahasa", theme: "Tema", light: "Terang", dark: "Gelap", coordinates: "Koordinat", idLabel: "ID", name: "Nama", year: "Tahun berdiri", businessType: "Jenis bisnis", activity: "Aktivitas data", recentActivity: "Perubahan terakhir", activityAll: "Semua aktivitas", activity7: "7 hari", activity30: "30 hari", activity90: "90 hari", activity365: "1 tahun", activityUnknown: "Belum ada event", score: "Skor perubahan", timeline: "Timeline perubahan", created: "Dibuat", updated: "Diperbarui", removed: "Tidak terlihat", addCategory: "Tambah kategori", categoryName: "Nama kategori baru", save: "Simpan", updateFailed: "Gagal memperbarui record.", view: "Lihat", edit: "Edit", exportCsv: "CSV", exportExcel: "Excel", refresh: "Refresh OSM", refreshQueued: "Menunggu...", refreshRunning: "Memperbarui OSM...", refreshCompleted: "Data OSM diperbarui", refreshFailed: "Refresh gagal", legalDetails: "Informasi legal", legalStatus: "Status legal", legalName: "Nama badan usaha", legalUnknown: "Belum ditemukan", legalUnverified: "Petunjuk, belum terverifikasi", legalVerified: "Terverifikasi", legalSource: "Bukti situs" },
  en: { title: "Business intelligence", source: "Live OSM dataset", mapped: "Mapped businesses", visible: "Visible now", explore: "Explore", categories: "categories", category: "Category", places: "Places", database: "Database", databaseTitle: "Database contents", databaseDescription: "Stored business records from OpenStreetMap", search: "Search name or ID...", showing: "Showing", of: "of", previous: "Previous", next: "Next", address: "Address", phone: "Phone", website: "Website", sourceLabel: "Source", close: "Close", noResults: "No matching records.", language: "Language", theme: "Theme", light: "Light", dark: "Dark", coordinates: "Coordinates", idLabel: "ID", name: "Name", year: "Established year", businessType: "Business type", activity: "Data activity", recentActivity: "Recent change", activityAll: "All activity", activity7: "7 days", activity30: "30 days", activity90: "90 days", activity365: "1 year", activityUnknown: "No event yet", score: "Change score", timeline: "Change timeline", created: "Created", updated: "Updated", removed: "Not observed", addCategory: "Add category", categoryName: "New category name", save: "Save", updateFailed: "Could not update record.", view: "View", edit: "Edit", exportCsv: "CSV", exportExcel: "Excel", refresh: "Refresh OSM", refreshQueued: "Queued...", refreshRunning: "Refreshing OSM...", refreshCompleted: "OSM data updated", refreshFailed: "Refresh failed", legalDetails: "Legal information", legalStatus: "Legal status", legalName: "Legal entity", legalUnknown: "Not found", legalUnverified: "Clue, unverified", legalVerified: "Verified", legalSource: "Website evidence" },
};
const prettyLabel = (value: string) => value.replace(/_/g, " ").replace(/\b\w/g, (char: string) => char.toUpperCase());
const categoryLabel = (value: string, language: Language) => categoryNames[value]?.[language] ?? prettyLabel(value);

function App() {
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [category, setCategory] = useState("all");
  const [businessType, setBusinessType] = useState("all");
  const [establishedYear, setEstablishedYear] = useState("all");
  const [activityDays, setActivityDays] = useState("all");
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
  const [newCategory, setNewCategory] = useState("");
  const [categoryStatus, setCategoryStatus] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState("");
  const mapNode = useRef<HTMLDivElement>(null);
  const map = useRef<Map | null>(null);
  const markers = useRef<Marker[]>([]);
  const t = copy[language];

  useEffect(() => { fetch(`${API}/businesses`).then((response) => response.json()).then((data) => setBusinesses(data.businesses)).catch(() => setError(language === "id" ? "Tidak dapat terhubung ke API." : "Could not connect to the API.")); }, [language]);
  useEffect(() => { fetch(`${API}/categories`).then((response) => response.json()).then((data) => setCategoryOptions(data.categories)).catch(() => undefined); }, []);
  useEffect(() => { localStorage.setItem("sbi-language", language); }, [language]);
  useEffect(() => { localStorage.setItem("sbi-theme", darkMode ? "dark" : "light"); }, [darkMode]);

  const categories = useMemo(() => ["all", ...Array.from(new Set([...businesses.map((business) => business.category), ...categoryOptions.map((item) => item.id)])).sort()], [businesses, categoryOptions]);
  const businessTypes = useMemo(() => ["all", ...Array.from(new Set(businesses.map((business) => business.business_type || business.subcategory))).filter(Boolean).sort()], [businesses]);
  const establishedYears = useMemo(() => ["all", ...Array.from(new Set(businesses.map((business) => business.established_year).filter((year): year is number => typeof year === "number"))).sort((a, b) => b - a).map(String)], [businesses]);
  const filtered = useMemo(() => businesses.filter((business) => {
    const recent = activityDays === "all" || (activityDays === "unknown" ? !business.activity?.last_event_at : Boolean(business.activity?.last_event_at && Date.now() - Date.parse(business.activity.last_event_at) <= Number(activityDays) * 86400000));
    return (category === "all" || business.category === category) && (businessType === "all" || (business.business_type || business.subcategory) === businessType) && (establishedYear === "all" || (establishedYear === "unknown" ? !business.established_year : String(business.established_year) === establishedYear)) && recent;
  }), [businesses, category, businessType, establishedYear, activityDays]);
  const placesPageSize = 50;
  const placesPageCount = Math.max(1, Math.ceil(filtered.length / placesPageSize));
  const placesPageIndex = Math.min(placesPage, placesPageCount - 1);
  const placesPageRows = filtered.slice(placesPageIndex * placesPageSize, (placesPageIndex + 1) * placesPageSize);
  const databaseRows = useMemo(() => {
    const query = databaseQuery.trim().toLowerCase();
    return businesses.filter((business) => (databaseCategory === "all" || business.category === databaseCategory) && (!query || business.name.toLowerCase().includes(query) || business.id.toLowerCase().includes(query)));
  }, [businesses, databaseQuery, databaseCategory]);
  const pageSize = 50;
  const pageCount = Math.max(1, Math.ceil(databaseRows.length / pageSize));
  const pageRows = databaseRows.slice(databasePage * pageSize, (databasePage + 1) * pageSize);

  useEffect(() => { setDatabasePage(0); }, [databaseQuery, databaseCategory, databaseTab]);
  useEffect(() => { setPlacesPage(0); }, [category, businessType, establishedYear, activityDays]);
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
      const marker = new maplibregl.Marker({ color: "#e76f51" }).setLngLat([business.location.longitude, business.location.latitude]).addTo(map.current!);
      marker.getElement().addEventListener("click", () => setSelected(business));
      return marker;
    });
  }, [filtered]);

  const displayCategory = (value: string) => categoryOptions.find((item) => item.id === value)?.name || categoryLabel(value, language);
  const selectBusiness = async (business: Business) => { setSelected(business); setActivityEvents([]); setDatabaseOpen(false); map.current?.flyTo({ center: [business.location.longitude, business.location.latitude], zoom: 16 }); try { const response = await fetch(`${API}/businesses/${encodeURIComponent(business.id)}/activities`); setActivityEvents((await response.json()).activities || []); } catch { setActivityEvents([]); } };
  const addCategory = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!newCategory.trim()) return;
    const response = await fetch(`${API}/categories`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: newCategory.trim() }) });
    if (response.ok) { const created = await response.json(); setCategoryOptions((current) => [...current, created]); setNewCategory(""); setCategoryStatus(created.name); }
    else setCategoryStatus(language === "id" ? "Kategori sudah ada atau tidak valid." : "Category already exists or is invalid.");
  };
  const updateBusinessCategory = async (businessId: string, value: string) => {
    const response = await fetch(`${API}/businesses/${encodeURIComponent(businessId)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ category: value }) });
    if (!response.ok) { setCategoryStatus(t.updateFailed); return; }
    const updated = await response.json();
    setBusinesses((current) => current.map((business) => business.id === updated.id ? updated : business));
    setCategoryStatus(language === "id" ? "Record diperbarui." : "Record updated.");
  };
  const exportHref = (format: "csv" | "xlsx") => {
    const params = new URLSearchParams();
    if (databaseCategory !== "all") params.set("category", databaseCategory);
    if (databaseQuery.trim()) params.set("q", databaseQuery.trim());
    return `${API}/export.${format}?${params.toString()}`;
  };
  const refreshOsm = async () => {
    if (refreshing) return;
    setRefreshing(true);
    setRefreshMessage(t.refreshQueued);
    try {
      const start = await fetch(`${API}/refresh`, { method: "POST" });
      if (!start.ok) throw new Error("Refresh request failed");
      for (let attempt = 0; attempt < 180; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const status = await (await fetch(`${API}/refresh/status`)).json();
        setRefreshMessage(status.status === "running" ? t.refreshRunning : t.refreshQueued);
        if (status.status === "completed") {
          const [businessResponse, categoryResponse] = await Promise.all([fetch(`${API}/businesses`), fetch(`${API}/categories`)]);
          setBusinesses((await businessResponse.json()).businesses);
          setCategoryOptions((await categoryResponse.json()).categories);
          setRefreshMessage(`${t.refreshCompleted}: ${status.normalized_business_count}`);
          setRefreshing(false);
          return;
        }
        if (status.status === "failed") throw new Error(status.error || "Refresh failed");
      }
      throw new Error("Refresh timed out");
    } catch {
      setRefreshMessage(t.refreshFailed);
      setRefreshing(false);
    }
  };

  return <div className={`app-shell ${darkMode ? "theme-dark" : ""}`}>
    <header className="topbar"><div><p className="eyebrow">KOTA SURAKARTA</p><h1>{t.title}</h1></div><nav className="top-actions" aria-label="Dashboard controls"><button className="refresh-button" onClick={refreshOsm} disabled={refreshing}>↻ <span>{refreshing ? refreshMessage : t.refresh}</span></button><button className="database-button" onClick={() => setDatabaseOpen(true)}>▦ <span>{t.database}</span></button><button className="language-toggle" onClick={() => setLanguage(language === "id" ? "en" : "id")} aria-label={`${t.language}: ${language.toUpperCase()}`}>{language === "id" ? "ID" : "EN"}</button><button className="theme-toggle" onClick={() => setDarkMode(!darkMode)} aria-label={`${t.theme}: ${darkMode ? t.dark : t.light}`}>{darkMode ? "☀" : "☾"}</button><div className="source-badge"><span className="status-dot" /> {t.source}</div></nav></header>
    <main className="dashboard">
      <aside className="sidebar">
        <section className="summary"><div><span className="metric-label">{t.mapped}</span><strong>{businesses.length.toLocaleString()}</strong></div><div><span className="metric-label">{t.visible}</span><strong>{filtered.length.toLocaleString()}</strong></div></section>
        <section className="filters"><div className="section-heading"><h2>{t.explore}</h2><span>{categories.length - 1} {t.categories}</span></div><label htmlFor="category">{t.category}</label><select id="category" value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map((item) => <option key={item} value={item}>{item === "all" ? categoryLabel(item, language) : displayCategory(item)}</option>)}</select><label htmlFor="business-type">{t.businessType}</label><select id="business-type" value={businessType} onChange={(event) => setBusinessType(event.target.value)}>{businessTypes.map((item) => <option key={item} value={item}>{item === "all" ? t.all : prettyLabel(item)}</option>)}</select><label htmlFor="established-year">{t.year}</label><select id="established-year" value={establishedYear} onChange={(event) => setEstablishedYear(event.target.value)}><option value="all">{t.all}</option>{establishedYears.slice(1).map((year) => <option key={year} value={year}>{year}</option>)}<option value="unknown">{t.unknownYear}</option></select><label htmlFor="activity-days">{t.recentActivity}</label><select id="activity-days" value={activityDays} onChange={(event) => setActivityDays(event.target.value)}><option value="all">{t.activityAll}</option><option value="7">{t.activity7}</option><option value="30">{t.activity30}</option><option value="90">{t.activity90}</option><option value="365">{t.activity365}</option><option value="unknown">{t.activityUnknown}</option></select></section>
        <section className="business-list"><div className="section-heading"><h2>{t.places}</h2><span>{filtered.length}</span></div>{error && <p className="error">{error}</p>}{placesPageRows.map((business) => <button className={`business-row ${selected?.id === business.id ? "selected" : ""}`} key={business.id} onClick={() => selectBusiness(business)}><span className="pin-dot" /><span><strong>{business.name}</strong><small>{categoryLabel(business.category, language)} · {prettyLabel(business.subcategory)}</small></span></button>)}<div className="places-pagination"><span>{filtered.length ? `${t.showing} ${placesPageIndex * placesPageSize + 1}-${Math.min((placesPageIndex + 1) * placesPageSize, filtered.length)} ${t.of} ${filtered.length}` : t.noResults}</span><div><button onClick={() => setPlacesPage((page) => Math.max(0, page - 1))} disabled={placesPageIndex === 0}>{t.previous}</button><span>{placesPageIndex + 1} / {placesPageCount}</span><button onClick={() => setPlacesPage((page) => Math.min(placesPageCount - 1, page + 1))} disabled={placesPageIndex >= placesPageCount - 1}>{t.next}</button></div></div></section>
      </aside>
      <section className="map-stage"><div ref={mapNode} className="map" />{selected && <article className="detail-panel"><button className="close" onClick={() => setSelected(null)} aria-label={t.close}>×</button><p className="eyebrow">{categoryLabel(selected.category, language)}</p><h2>{selected.name}</h2><p className="detail-subtitle">{prettyLabel(selected.subcategory)}</p><div className="detail-lines">{selected.address["addr:street"] && <p><span>{t.address}</span>{[selected.address["addr:housenumber"], selected.address["addr:street"], selected.address["addr:suburb"]].filter(Boolean).join(" ")}</p>}{selected.contact.phone && <p><span>{t.phone}</span>{selected.contact.phone}</p>}{selected.contact.website && <p><span>{t.website}</span><a href={selected.contact.website} target="_blank" rel="noreferrer">{selected.contact.website}</a></p>}<div className="legal-details"><span>{t.legalDetails}</span><p><span>{t.legalStatus}</span>{selected.legal?.status === "verified" ? t.legalVerified : selected.legal?.status === "unverified" ? t.legalUnverified : t.legalUnknown}</p>{selected.legal?.entity_name && <p><span>{t.legalName}</span>{selected.legal.entity_name} ({selected.legal.entity_type})</p>}{selected.legal?.evidence?.[0]?.url && <p><span>{t.legalSource}</span><a href={selected.legal.evidence[0].url} target="_blank" rel="noreferrer">{new URL(selected.legal.evidence[0].url).hostname}</a></p>}</div><p><span>{t.activity}</span>{selected.active === false ? t.removed : selected.activity?.last_event_type ? `${selected.activity.last_event_type} · ${selected.activity.score ?? 0}` : t.activityUnknown}</p><p><span>{t.sourceLabel}</span>OpenStreetMap · {selected.metadata.osm_type} {selected.metadata.osm_id}</p><div className="activity-timeline"><span>{t.timeline}</span>{activityEvents.slice().reverse().slice(0, 8).map((event) => <small key={`${event.type}-${event.detected_at}`}>{event.detected_at.slice(0, 10)} · {event.type}</small>)}</div></div></article>}</section>
    </main>
    {databaseOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDatabaseOpen(false); }}><section className="database-modal" role="dialog" aria-modal="true" aria-labelledby="database-title"><div className="modal-header"><div><p className="eyebrow">JSON DATABASE</p><h2 id="database-title">{t.databaseTitle}</h2><p className="modal-description">{t.databaseDescription}</p></div><button className="close" onClick={() => setDatabaseOpen(false)} aria-label={t.close}>×</button></div><div className="database-tabs" role="tablist"><button className={databaseTab === "view" ? "active" : ""} onClick={() => setDatabaseTab("view")} role="tab" aria-selected={databaseTab === "view"}>{t.view}</button><button className={databaseTab === "edit" ? "active" : ""} onClick={() => setDatabaseTab("edit")} role="tab" aria-selected={databaseTab === "edit"}>{t.edit}</button></div>{databaseTab === "edit" ? <form className="category-form" onSubmit={addCategory}><input value={newCategory} onChange={(event) => setNewCategory(event.target.value)} placeholder={t.categoryName} aria-label={t.categoryName} /><button type="submit">+ {t.addCategory}</button>{categoryStatus && <span>{categoryStatus}</span>}</form> : <div className="database-view-filter"><label htmlFor="database-category-filter">{t.category}</label><select id="database-category-filter" value={databaseCategory} onChange={(event) => setDatabaseCategory(event.target.value)}><option value="all">{t.all}</option>{categoryOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>}<div className="database-toolbar"><input className="database-search" value={databaseQuery} onChange={(event) => setDatabaseQuery(event.target.value)} placeholder={t.search} aria-label={t.search} /><div className="export-actions"><a href={exportHref("csv")} download>{t.exportCsv}</a><a href={exportHref("xlsx")} download>{t.exportExcel}</a></div></div><div className="database-table-wrap"><table><thead><tr><th>{t.idLabel}</th><th>{t.name}</th><th>{t.category}</th><th>{t.businessType}</th><th>{t.year}</th><th>{t.coordinates}</th><th>{t.sourceLabel}</th></tr></thead><tbody>{pageRows.map((business) => <tr key={business.id} onClick={() => selectBusiness(business)}><td className="mono">{business.id}</td><td><strong>{business.name}</strong><small>{prettyLabel(business.subcategory)}</small></td><td onClick={(event) => event.stopPropagation()}>{databaseTab === "edit" ? <select className="database-category" value={business.category} onChange={(event) => updateBusinessCategory(business.id, event.target.value)}>{categoryOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select> : displayCategory(business.category)}</td><td>{prettyLabel(business.business_type || business.subcategory)}</td><td>{business.established_year || "-"}</td><td className="mono">{business.location.latitude.toFixed(4)}, {business.location.longitude.toFixed(4)}</td><td>OSM {business.metadata.osm_type} {business.metadata.osm_id}</td></tr>)}</tbody></table>{pageRows.length === 0 && <p className="empty-state">{t.noResults}</p>}</div><div className="modal-footer"><span>{t.showing} {databaseRows.length === 0 ? 0 : databasePage * pageSize + 1}-{Math.min((databasePage + 1) * pageSize, databaseRows.length)} {t.of} {databaseRows.length}</span><div><button onClick={() => setDatabasePage(Math.max(0, databasePage - 1))} disabled={databasePage === 0}>‹ {t.previous}</button><span className="page-number">{databasePage + 1} / {pageCount}</span><button onClick={() => setDatabasePage(Math.min(pageCount - 1, databasePage + 1))} disabled={databasePage >= pageCount - 1}>{t.next} ›</button></div></div></section></div>}
  </div>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
