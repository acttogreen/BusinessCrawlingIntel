import { useEffect, useRef, useState } from "react";

const API = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
type Language = "id" | "en";

type Props = { language: Language; onClose: () => void };

type PreferenceSnapshot = {
  provider: string;
  model: string;
  endpoint: string;
  batch_size: number;
  timeout_seconds: number;
  retry_count: number;
  confidence: number;
  ruleset: string;
  web_lookup: boolean;
  token_configured: boolean;
};

let cachedPreferences: PreferenceSnapshot | null = null;

const defaultCompanySchema = `{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "CompanyData",
  "description": "Skema untuk data ekstraksi profil perusahaan/entitas bisnis",
  "type": "object",
  "properties": {
    "company_name": { "type": "string", "description": "Nama resmi perusahaan atau usaha tanpa menyertakan entitas hukum" },
    "legal_entity": { "type": "string", "description": "Bentuk badan hukum perusahaan (misal: PT, CV, UD, dll)", "enum": ["PT", "CV", "UD", "PO", "PD", "BLU", "YAYASAN", "KOPERASI", "PERORANGAN", "PERSERO", "Instansi Pemerintah", "Pasar Daerah", "Komunitas"] },
    "address": { "type": "string", "description": "Alamat lengkap jalan, nomor, RT/RW, dan kelurahan" },
    "district": { "type": "string", "description": "Nama kecamatan lokasi perusahaan" },
    "city": { "type": "string", "description": "Nama kota atau kabupaten" },
    "province": { "type": "string", "description": "Nama provinsi" },
    "business_sector": { "type": "string", "description": "Sektor usaha atau bidang industri utama beserta kualifikasinya jika ada" },
    "source_url": { "type": "string", "format": "uri", "description": "URL sumber acuan data" },
    "evidence": { "type": "string", "description": "Konteks atau teks bukti pendukung ekstraksi dari dokumen/sumber" },
    "investment_type": { "type": "string", "description": "Jenis penanaman modal", "enum": ["PMDN", "PMA", "Instansi Pemerintah"] },
    "phone_number": { "type": "string", "description": "Nomor telepon/kontak yang dapat dihubungi" }
  },
  "required": ["company_name", "legal_entity", "address", "district", "city", "province", "business_sector", "source_url", "evidence", "investment_type", "phone_number"],
  "additionalProperties": false
}`;

const defaultOsmMapping = `{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "BusinessDatabaseMapping",
  "description": "Schema payload mapping data registry perusahaan dengan hasil pencocokan OpenStreetMap.",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "primary_source", "mapping_source", "source_files", "generated_at", "summary", "businesses"],
  "properties": {
    "schema_version": { "type": "string" },
    "primary_source": { "type": "string" },
    "mapping_source": { "type": "string", "const": "openstreetmap" },
    "source_files": {
      "type": "object",
      "additionalProperties": false,
      "required": ["registry", "osm"],
      "properties": { "registry": { "type": "string" }, "osm": { "type": "string" } }
    },
    "generated_at": { "type": "string", "format": "date-time" },
    "summary": {
      "type": "object",
      "additionalProperties": false,
      "required": ["total", "matched", "unmatched"],
      "properties": {
        "total": { "type": "integer", "minimum": 0 },
        "matched": { "type": "integer", "minimum": 0 },
        "unmatched": { "type": "integer", "minimum": 0 }
      }
    },
    "businesses": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "name", "registry", "osm", "provenance"],
        "properties": {
          "id": { "type": "string" },
          "name": { "type": "string" },
          "registry": {
            "type": "object",
            "additionalProperties": false,
            "required": ["company_name", "legal_entity", "address", "district", "city", "province", "business_sector", "source_url", "evidence", "investment_type"],
            "properties": {
              "company_name": { "type": "string" }, "legal_entity": { "type": "string" }, "address": { "type": "string" },
              "district": { "type": "string" }, "city": { "type": "string" }, "province": { "type": "string" },
              "business_sector": { "type": "string" }, "source_url": { "type": "string", "format": "uri" },
              "evidence": { "type": "string" }, "investment_type": { "type": "string" }, "phone_number": { "type": "string" }
            }
          },
          "osm": {
            "type": "object",
            "additionalProperties": false,
            "required": ["status", "match_method", "confidence", "source"],
            "properties": {
              "status": { "type": "string", "enum": ["matched", "unmatched"] }, "match_method": { "type": "string" },
              "confidence": { "type": "number", "minimum": 0, "maximum": 1 }, "source": { "type": "string" },
              "source_id": { "type": "string" }, "osm_type": { "type": "string" }, "osm_id": { "type": "integer" }, "name": { "type": "string" },
              "location": { "type": "object", "additionalProperties": false, "required": ["latitude", "longitude"], "properties": { "latitude": { "type": "number" }, "longitude": { "type": "number" } } },
              "address": { "type": "object", "additionalProperties": true }, "tags": { "type": "object", "additionalProperties": true }, "last_seen_at": { "type": "string", "format": "date-time" }
            }
          },
          "provenance": {
            "type": "object",
            "additionalProperties": false,
            "required": ["primary_source", "mapping_source", "mapped_at"],
            "properties": { "primary_source": { "type": "string" }, "mapping_source": { "type": "string" }, "mapped_at": { "type": "string", "format": "date-time" } }
          }
        }
      }
    }
  }
}`;

export function SettingsModal({ language, onClose }: Props) {
  const id = language === "id";
  const [provider, setProvider] = useState(cachedPreferences?.provider || "custom");
  const [model, setModel] = useState(cachedPreferences?.model || "gpt-4o-mini");
  const [token, setToken] = useState("");
  const [tokenConfigured, setTokenConfigured] = useState(cachedPreferences?.token_configured || false);
  const [endpoint, setEndpoint] = useState(cachedPreferences?.endpoint || "");
  const [batchSize, setBatchSize] = useState(String(cachedPreferences?.batch_size || 5));
  const [timeoutSeconds, setTimeoutSeconds] = useState(String(cachedPreferences?.timeout_seconds || 180));
  const [retryCount, setRetryCount] = useState(String(cachedPreferences?.retry_count ?? 2));
  const [confidence, setConfidence] = useState(String(cachedPreferences?.confidence ?? 0.75));
  const [webLookup, setWebLookup] = useState(cachedPreferences?.web_lookup || false);
  const [ruleset, setRuleset] = useState("");
  const [companySchema, setCompanySchema] = useState(defaultCompanySchema);
  const [osmMapping, setOsmMapping] = useState(defaultOsmMapping);
  const [showToken, setShowToken] = useState(false);
  const [message, setMessage] = useState("");
  const [checkingToken, setCheckingToken] = useState(false);
  const [loadingSettings, setLoadingSettings] = useState(true);
  const [logs, setLogs] = useState<Array<{ type: "info" | "success" | "error"; text: string }>>([]);
  const logWindowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    const checkSavedToken = async () => {
      addLog("info", id ? "Memuat pengaturan tersimpan dari .env..." : "Loading saved settings from .env...");
      try {
        const settingsResponse = await fetch(`${API}/api/preferences`, { cache: "no-store" });
        const settings = await settingsResponse.json().catch(() => ({}));
        const rulesetResponse = await fetch(`${API}/api/preferences/ruleset`, { cache: "no-store" });
        const rulesetResult = await rulesetResponse.json().catch(() => ({}));
        if (!cancelled && settingsResponse.ok) {
          const snapshot: PreferenceSnapshot = {
            provider: settings.provider || "custom",
            model: settings.model || "gpt-4o-mini",
            endpoint: settings.endpoint || "",
            batch_size: Number(settings.batch_size ?? 5),
            timeout_seconds: Number(settings.timeout_seconds ?? 180),
            retry_count: Number(settings.retry_count ?? 2),
            confidence: Number(settings.confidence ?? 0.75),
            ruleset: rulesetResponse.ok ? String(rulesetResult.ruleset || "") : "",
            web_lookup: Boolean(settings.web_lookup),
            token_configured: Boolean(settings.token_configured),
          };
          cachedPreferences = snapshot;
          addLog("info", `Loaded values: model=${snapshot.model || "(empty)"}, endpoint=${snapshot.endpoint || "(empty)"}, token=${snapshot.token_configured ? "configured" : "not configured"}`);
          setProvider(snapshot.provider);
          setModel(snapshot.model);
          setTokenConfigured(snapshot.token_configured);
          setEndpoint(snapshot.endpoint);
          setBatchSize(String(snapshot.batch_size));
          setTimeoutSeconds(String(snapshot.timeout_seconds));
          setRetryCount(String(snapshot.retry_count));
          setConfidence(String(snapshot.confidence));
          setWebLookup(snapshot.web_lookup);
          setRuleset(snapshot.ruleset);
          addLog("success", "Loaded saved settings from backend preferences");
        }
        const response = await fetch(`${API}/api/preferences/curation-status`, { cache: "no-store" });
        const result = await response.json().catch(() => ({}));
        if (cancelled) return;
        const detail = result.message || (result.connected ? "Token valid" : "Token belum dikonfigurasi");
        addLog(result.connected ? "success" : "error", `${result.connected ? "SUCCESS" : "ERROR"}: ${detail}`);
        setMessage(result.connected ? (id ? "Token tersimpan dan koneksi tersedia." : "Saved token is connected.") : detail);
      } catch {
        if (!cancelled) {
          addLog("error", id ? "ERROR: Backend tidak dapat dihubungi" : "ERROR: Backend could not be reached");
          setMessage(id ? "Backend tidak dapat dihubungi." : "Backend could not be reached.");
        }
      } finally {
        if (!cancelled) setLoadingSettings(false);
      }
    };
    void checkSavedToken();
    return () => { cancelled = true; };
  }, [id]);
  useEffect(() => { logWindowRef.current?.scrollTo({ top: logWindowRef.current.scrollHeight, behavior: "smooth" }); }, [logs]);

  const addLog = (type: "info" | "success" | "error", text: string) => {
    const time = new Date().toLocaleTimeString([], { hour12: false });
    setLogs((current) => [...current, { type, text: `[${time}] ${text}` }]);
  };

  const checkToken = async () => {
    if (!token.trim() && !tokenConfigured && !["ollama", "local"].includes(provider)) { addLog("error", id ? "ERROR: Token API belum diisi" : "ERROR: API token is empty"); setMessage(id ? "Isi token API terlebih dahulu, kecuali untuk Ollama/LLM lokal." : "Enter an API token first, except for Ollama/local LLM."); return; }
    setCheckingToken(true); setMessage(id ? "Memeriksa koneksi token…" : "Checking token connection…");
    addLog("info", `Checking connection to ${provider.toUpperCase()} API (${model})...`);
    try {
      const response = await fetch(`${API}/api/preferences/check-token`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider, token: token.trim(), endpoint: endpoint.trim() }) });
      const result = await response.json().catch(() => ({}));
      const detail = result.message || (response.ok ? "Token valid" : "Invalid API key / Unauthorized");
      addLog(response.ok ? "success" : "error", `${response.ok ? "SUCCESS" : "ERROR"}: ${detail} (Status: ${response.status})`);
      setMessage(detail);
    } catch { addLog("error", id ? "ERROR: Backend/provider tidak dapat dihubungi" : "ERROR: Backend/provider could not be reached"); setMessage(id ? "Backend/provider tidak dapat dihubungi." : "Backend/provider could not be reached."); }
    finally { setCheckingToken(false); }
  };

  const copySchema = async (schema: string) => {
    try { await navigator.clipboard.writeText(schema); setMessage(id ? "Schema berhasil disalin." : "Schema copied."); }
    catch { setMessage(id ? "Schema gagal disalin." : "Could not copy schema."); }
  };

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    let parsedCompanySchema: Record<string, unknown>;
    let parsedOsmMapping: Record<string, unknown>;
    try { parsedCompanySchema = JSON.parse(companySchema) as Record<string, unknown>; } catch { setMessage(id ? "Company schema JSON tidak valid." : "Company schema JSON is invalid."); return; }
    try { parsedOsmMapping = JSON.parse(osmMapping) as Record<string, unknown>; } catch { setMessage(id ? "OSM mapping JSON tidak valid." : "OSM mapping JSON is invalid."); return; }
    const candidateSchema = parsedCompanySchema;
    const requiredFields = ["company_name", "legal_entity", "address", "district", "city", "province", "business_sector", "source_url", "evidence", "investment_type", "phone_number"];
    const schemaProperties = candidateSchema && typeof candidateSchema.properties === "object" && candidateSchema.properties !== null ? candidateSchema.properties as Record<string, unknown> : null;
    if (!candidateSchema || !schemaProperties || requiredFields.some((field) => !(field in schemaProperties))) {
      setMessage(id ? "Schema harus memiliki company_candidates dan seluruh field ekstraksi perusahaan." : "Schema must include company_candidates and all company extraction fields.");
      return;
    }
    try {
      const rulesetResponse = await fetch(`${API}/api/preferences/ruleset`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ruleset }) });
      const rulesetResult = await rulesetResponse.json().catch(() => ({}));
      if (!rulesetResponse.ok) throw new Error(typeof rulesetResult.detail === "string" ? rulesetResult.detail : `Ruleset HTTP ${rulesetResponse.status}`);
      const response = await fetch(`${API}/api/preferences`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider, model, token: token.trim(), endpoint: endpoint.trim(), batch_size: Number(batchSize), timeout_seconds: Number(timeoutSeconds), retry_count: Number(retryCount), confidence: Number(confidence), web_lookup: webLookup, mapping: { company_candidates: parsedCompanySchema, osm: parsedOsmMapping } }) });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : `HTTP ${response.status}`);
      cachedPreferences = {
        provider,
        model,
        endpoint: endpoint.trim(),
        batch_size: Number(batchSize),
        timeout_seconds: Number(timeoutSeconds),
        retry_count: Number(retryCount),
        confidence: Number(confidence),
        ruleset,
        web_lookup: webLookup,
        token_configured: Boolean(token.trim()) || tokenConfigured,
      };
      setTokenConfigured(cachedPreferences.token_configured);
      setMessage(id ? "Token berhasil disimpan ke .env lokal." : "Token saved to the local .env file.");
      addLog("success", id ? "SUCCESS: Token tersimpan di .env." : "SUCCESS: Token saved to .env.");
      localStorage.removeItem("sbi-ai-token");
      localStorage.removeItem("sbi-ai-provider");
      localStorage.removeItem("sbi-ai-model");
      localStorage.removeItem("sbi-curation-batch-size");
      localStorage.removeItem("sbi-curation-confidence");
      localStorage.removeItem("sbi-osm-mapping");
      onClose();
    } catch (error) { const detail = error instanceof Error ? error.message : "Unknown error"; setMessage(id ? `Gagal menyimpan preferences: ${detail}` : `Could not save preferences: ${detail}`); }
  };

  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <form className="settings-modal" onSubmit={save} role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <div className="modal-header"><p className="eyebrow">CONFIGURATION</p><h2 id="settings-title">{id ? "Pengaturan AI & OSM" : "AI & OSM settings"}</h2><p className="modal-description">{id ? "Konfigurasi lokal untuk kurasi kandidat perusahaan dan mapping JSON." : "Local configuration for company candidate curation and JSON mapping."}</p><button type="button" className="close" onClick={onClose} aria-label={id ? "Tutup" : "Close"}>×</button></div>
      <div className="settings-body">{loadingSettings && <p className="settings-loading" role="status">{id ? "Memuat konfigurasi tersimpan…" : "Loading saved configuration…"}</p>}
        <section className="settings-section"><h3>{id ? "Provider AI" : "AI provider"}</h3><p>{id ? "Token dienkripsi dan disimpan sebagai file preferences di backend." : "The token is encrypted and stored as a backend preferences file."}</p><div className="settings-grid"><label>Provider<select value={provider} onChange={(e) => setProvider(e.target.value)}><option value="openai">OpenAI</option><option value="groq">Groq</option><option value="together">Together AI</option><option value="ollama">Ollama (lokal)</option><option value="custom">Custom / OpenAI-compatible</option></select></label><label>Model<input value={model} onChange={(e) => setModel(e.target.value)} placeholder="gpt-4o-mini" /></label></div><label>Endpoint API / LLM lokal<input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder={provider === "ollama" ? "http://127.0.0.1:11434/v1" : "https://api.example.com/v1"} /></label><label>API token<div className="token-field"><input type={showToken ? "text" : "password"} value={token} onChange={(e) => { setToken(e.target.value); setTokenConfigured(false); }} placeholder={tokenConfigured ? (id ? "Token tersimpan — kosongkan untuk mempertahankan" : "Token saved — leave empty to keep it") : "sk-..."} autoComplete="off" /><button type="button" onClick={() => setShowToken(!showToken)}>{showToken ? "Hide" : "Show"}</button></div></label><button type="button" className="settings-check-token settings-action-button" onClick={checkToken} disabled={checkingToken}>{checkingToken ? (id ? "Memeriksa…" : "Checking…") : (id ? "Cek koneksi token" : "Check token connection")}</button><div className="config-log-window" ref={logWindowRef} role="log" aria-live="polite">{logs.length === 0 ? <span className="config-log-placeholder">{id ? "Belum ada aktivitas koneksi." : "No connection activity yet."}</span> : logs.map((log, index) => <div key={`${log.text}-${index}`} className={`config-log-entry-${log.type}`}>{log.text}</div>)}</div><button type="button" className="config-log-clear" onClick={() => setLogs([])} disabled={!logs.length}>{id ? "Bersihkan log" : "Clear log"}</button></section>
        <section className="settings-section"><h3>{id ? "Kurasi company candidates" : "Company candidate curation"}</h3><p>{id ? "Gunakan AI sebagai bantuan review; jangan menganggap hasil sebagai verifikasi legal." : "Use AI as review assistance; do not treat results as legal verification."}</p><div className="settings-grid"><label>{id ? "Ukuran batch" : "Batch size"}<input type="number" min="1" max="200" value={batchSize} onChange={(e) => setBatchSize(e.target.value)} /><small>{id ? "Batas kandidat per batch; payload besar otomatis dipecah." : "Candidate limit per batch; large payloads are split automatically."}</small></label><label>{id ? "Timeout request (detik)" : "Request timeout (seconds)"}<input type="number" min="30" max="600" value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(e.target.value)} /></label><label>{id ? "Percobaan ulang" : "Retries"}<input type="number" min="0" max="5" value={retryCount} onChange={(e) => setRetryCount(e.target.value)} /></label><label className="confidence-control"><span className="confidence-label">{id ? "Confidence minimum" : "Minimum confidence"}<output className="confidence-value" htmlFor="minimum-confidence">{Number(confidence).toFixed(2)}</output></span><input id="minimum-confidence" className="confidence-slider" type="range" min="0" max="1" step="0.05" value={confidence} onChange={(e) => setConfidence(e.target.value)} /><span className="confidence-scale"><span>0</span><span>1</span></span></label></div></section>
        <section className="settings-section"><div className="schema-heading"><div><h3>{id ? "Ruleset evidence & verifikasi internet" : "Evidence ruleset & web verification"}</h3><p>{id ? "Aturan prompt untuk sektor usaha terdekat dan verifikasi riwayat pendanaan asing." : "Prompt rules for nearest business-sector matching and foreign-funding verification."}</p></div></div><label className="checkbox-label"><input type="checkbox" checked={webLookup} onChange={(e) => setWebLookup(e.target.checked)} /> {id ? "Izinkan pencarian internet untuk sektor & pendanaan" : "Allow web lookup for sector and funding"}</label><textarea className="ruleset-editor" value={ruleset} onChange={(e) => setRuleset(e.target.value)} spellCheck={false} rows={18} aria-label="Evidence curation ruleset" /></section>
        <section className="settings-section"><div className="schema-heading"><div><h3>JSON schema → company candidates</h3><p>{id ? "Schema standar ekstraksi profil perusahaan." : "Standard company profile extraction schema."}</p></div><button type="button" className="schema-copy-button" onClick={() => copySchema(companySchema)}>{id ? "Salin schema" : "Copy schema"}</button></div><textarea className="schema-code-block" value={companySchema} onChange={(e) => setCompanySchema(e.target.value)} spellCheck={false} rows={14} aria-label="Company candidates JSON schema" /></section>
        <section className="settings-section"><div className="schema-heading"><div><h3>JSON OSM mapping</h3><p>{id ? "Pengaturan mapping field OSM ke kandidat perusahaan." : "Configure OSM field mapping for company candidates."}</p></div><button type="button" className="schema-copy-button" onClick={() => copySchema(osmMapping)}>{id ? "Salin schema" : "Copy schema"}</button></div><textarea className="mapping-editor" value={osmMapping} onChange={(e) => setOsmMapping(e.target.value)} spellCheck={false} rows={14} aria-label="OSM mapping JSON schema" /></section>
      </div><div className="settings-footer"><span className={message.includes("valid") || message.includes("wajib") || message.includes("required") || message.includes("invalid") ? "settings-error" : "settings-success"}>{message}</span><div><button type="button" className="settings-cancel" onClick={onClose}>{id ? "Batal" : "Cancel"}</button><button type="submit" className="settings-save">{id ? "Simpan pengaturan" : "Save settings"}</button></div></div>
    </form>
  </div>;
}
