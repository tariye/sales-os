const API = "/api";
const $ = id => document.getElementById(id);
const esc = v => String(v ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const VIEW_KEY = "info-analyzer.active-view.v1";
const VIEW_QUERY_KEY = "view";
const DEFAULT_VIEW = "overview";
const VIEWS = new Set([
  "overview",
  "capture",
  "human-review",
  "sources",
  "evidence",
  "system-health",
  "alert-center",
  "stock-intel",
  "jobs-runs",
  "build-information",
  "legacy-archive",
  "help",
]);

let buildInfo = null;
let runtimeStatusData = null;
let latestCapturedObservation = null;
let latestProcessedSignal = null;
let overviewData = null;
let sourcesData = null;
let latestCreatedSourceId = "";
let evidenceData = null;
let healthData = null;
let jobsRunsData = null;
let legacyData = null;
let stockIntelData = null;
let stockIntelLoading = false;
let stockIntelTimer = null;
let stockWatchlist = [];
let alertsData = null;
let localSourceData = null;
let alertCheckResult = null;
let currentAlertReviewId = null;
let isLoadingAlertReviews = false;
let isSubmittingAlertVerdict = false;
const STOCK_WATCHLIST_KEY = "info-analyzer.stock-watchlist.v1";
const STOCK_SNAPSHOT_MODE_KEY = "info-analyzer.stock-snapshot-mode.v1";
const DEFAULT_STOCK_WATCHLIST = ["AAPL", "NVDA", "MSFT"];
const bootstrapData = window.__CUTOVER_BOOTSTRAP__ || null;
const pathInitialView = window.location.pathname === "/dump" ? "capture" : "";
const bootstrapInitialView = normalizeView(pathInitialView || new URLSearchParams(window.location.search).get(VIEW_QUERY_KEY) || new URLSearchParams(window.location.search).get("tab") || "");

function api(path, opts = {}) {
  return fetch(API + path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
  }).then(async res => {
    const txt = await res.text();
    const data = txt ? JSON.parse(txt) : {};
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  });
}

function toast(msg) {
  const el = $("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => el.classList.add("hidden"), 2400);
}

function nextPaint() {
  return new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 0)));
}

async function visibleFeedbackDelay() {
  await nextPaint();
  await new Promise(resolve => setTimeout(resolve, 120));
}

function fmtDate(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  try {
    return new Intl.DateTimeFormat("en-US", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(d);
  } catch (err) {
    return d.toLocaleString();
  }
}

function fmtMoney(value, currency = "USD") {
  const n = Number(value);
  if (!Number.isFinite(n)) return "n/a";
  try {
    if (currency && currency !== "USD") {
      return `${n.toFixed(2)} ${currency}`;
    }
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 2,
    }).format(n);
  } catch (err) {
    return currency && currency !== "USD" ? `${n.toFixed(2)} ${currency}` : `$${n.toFixed(2)}`;
  }
}

function fmtPct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "n/a";
  const sign = n > 0 ? "+" : "";
  return `${sign}${(n * 100).toFixed(1)}%`;
}

function prettyLabel(value) {
  return String(value ?? "")
    .trim()
    .replace(/\b\w/g, ch => ch.toUpperCase()) || "n/a";
}

function fmtAge(value) {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return "";
  if (n < 60) return `${Math.round(n)}s`;
  const mins = Math.floor(n / 60);
  if (mins < 60) return `${mins}m ${Math.round(n % 60)}s`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ${mins % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

function statHTML(value, label) {
  return `<div class="stat"><strong>${esc(value ?? "n/a")}</strong><span class="muted">${esc(label)}</span></div>`;
}

function statGroupHTML(title, items, hint = "") {
  return `
    <section class="cockpit-group">
      <div class="cockpit-group-head">
        <div>
          <p class="eyebrow">${esc(title)}</p>
          ${hint ? `<p class="muted">${esc(hint)}</p>` : ""}
        </div>
        <span class="cockpit-group-count">${items.length}</span>
      </div>
      <div class="stats cockpit-stats-grid">
        ${items.join("")}
      </div>
    </section>
  `;
}

function kvHTML(label, value) {
  return value || value === 0 ? `<div class="kv"><b>${esc(label)}</b><span>${esc(value)}</span></div>` : "";
}

function setRuntimeBanner(kind, title, detail) {
  const banner = $("runtimeStatusBanner");
  if (!banner) return;
  banner.className = `banner banner-${kind}`;
  if ($("runtimeConnection")) $("runtimeConnection").textContent = title;
  if ($("runtimeLastApiStatus")) $("runtimeLastApiStatus").textContent = detail;
}

function renderRuntimeStatus(data) {
  runtimeStatusData = data;
  setRuntimeBanner("success", "Connected", `Last API status: ${data.last_api_status || "ok"} at ${fmtDate(data.generated_at)}`);
  updateCaptureConnectionFromRuntime();
  const scheduler = data.data_plane?.scheduler || {};
  const worker = (data.data_plane?.workers || [])[0] || {};
  if ($("runtimeStatusStats")) {
    $("runtimeStatusStats").innerHTML = [
      statHTML(data.git_branch || "n/a", "Branch"),
      statHTML((data.git_commit || "unavailable").slice(0, 12), "Build SHA"),
      statHTML(data.environment || "local", "Environment"),
      statHTML(data.sqlite?.quick_check || "n/a", "SQLite"),
      statHTML(data.active_db_path_category || "n/a", "Active DB"),
      statHTML(data.test_db_configured ? "configured" : "default", "Test DB"),
      statHTML(scheduler.owner_id || "unassigned", "Scheduler"),
      statHTML(worker.heartbeat_at ? fmtDate(worker.heartbeat_at) : "no heartbeat", "Worker"),
    ].join("");
  }
  if ($("runtimeStatusDetails")) {
    $("runtimeStatusDetails").innerHTML = `
      <div class="item">
        <h3>Runtime Identity</h3>
        ${kvHTML("Repository", data.repository_root || "")}
        ${kvHTML("Active DB Path", data.active_db_path || "")}
        ${kvHTML("Test DB Path", data.test_db_path || "")}
        ${kvHTML("Test DB ID", data.test_db_id || "")}
        ${kvHTML("Version", data.application_version || "")}
        ${kvHTML("Schema", data.schema_version ?? "")}
      </div>
    `;
  }
}

function renderRuntimeDisconnected(error) {
  runtimeStatusData = null;
  setRuntimeBanner("error", "Disconnected", `Last API status: failed. ${error?.message || "The server did not respond."}`);
  updateCaptureConnectionFromRuntime();
  if ($("runtimeStatusStats")) {
    $("runtimeStatusStats").innerHTML = [
      statHTML("disconnected", "Server"),
      statHTML("unknown", "Build SHA"),
      statHTML("unknown", "Active DB"),
      statHTML("unknown", "Test DB"),
    ].join("");
  }
  if ($("runtimeStatusDetails")) {
    $("runtimeStatusDetails").innerHTML = `
      <div class="item error">
        <h3>Server unavailable</h3>
        <p class="muted">Start the local runtime with scripts/start_local.sh, then reopen this URL.</p>
      </div>
    `;
  }
}

function normalizeView(view) {
  return VIEWS.has(view) ? view : DEFAULT_VIEW;
}

function readViewFromUrl() {
  const params = new URLSearchParams(window.location.search);
  return normalizeView(pathInitialView || params.get(VIEW_QUERY_KEY) || params.get("tab") || "");
}

function readSavedView() {
  try {
    return normalizeView(localStorage.getItem(VIEW_KEY) || "");
  } catch (err) {
    return DEFAULT_VIEW;
  }
}

function persistView(view) {
  const next = normalizeView(view);
  try {
    localStorage.setItem(VIEW_KEY, next);
  } catch (err) {}
  try {
    const params = new URLSearchParams(window.location.search);
    params.set(VIEW_QUERY_KEY, next);
    params.delete("tab");
    history.replaceState({}, "", `${window.location.pathname}?${params.toString()}${window.location.hash || ""}`);
  } catch (err) {}
}

function setActiveView(view) {
  const next = normalizeView(view);
  if (next !== "stock-intel") stopStockIntelAutoRefresh();
  persistView(next);
  document.querySelectorAll(".tab").forEach(btn => btn.classList.toggle("active", btn.dataset.view === next));
  document.querySelectorAll(".panel").forEach(panel => panel.classList.toggle("active", panel.id === next));
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (next === "overview") {
    loadRuntimeStatus();
    loadOverview();
  }
  if (next === "capture") {
    loadRuntimeStatus();
    loadRecentCaptures();
    loadContextLibrary();
  }
  if (next === "human-review") loadTestModeStatus();
  if (next === "human-review") loadAlertReviews();
  if (next === "sources") loadSources();
  if (next === "evidence") loadEvidence();
  if (next === "system-health") loadSystemHealth();
  if (next === "alert-center") {
    loadAlerts();
    loadLocalSourceStatus();
  }
  if (next === "stock-intel") {
    startStockIntelAutoRefresh();
    loadStockIntel();
  }
  if (next === "jobs-runs") loadJobsRuns();
  if (next === "build-information") loadBuildInformation();
  if (next === "legacy-archive") loadLegacyArchive();
}

async function refreshBuildInfo() {
  const liveBuildInfo = await api("/build-info");
  buildInfo = bootstrapData ? {
    ...bootstrapData,
    ...liveBuildInfo,
    manifest: liveBuildInfo.manifest || bootstrapData.manifest,
    feature_registry: liveBuildInfo.feature_registry || bootstrapData.feature_registry,
    overview: liveBuildInfo.overview || bootstrapData.overview,
    worker: liveBuildInfo.worker || bootstrapData.worker || liveBuildInfo.workers?.[0] || bootstrapData.workers?.[0] || null,
    scheduler: liveBuildInfo.scheduler || bootstrapData.scheduler,
  } : liveBuildInfo;
  const appVersion = buildInfo.application_version || "";
  const commit = buildInfo.git_commit || "unavailable";
  const schema = buildInfo.schema_version || "";
  if ($("appVersion")) $("appVersion").textContent = appVersion;
  document.title = `Info Analyzer OS ${appVersion || ""}`.trim();
  return { appVersion, commit, schema };
}

async function loadRuntimeStatus() {
  try {
    const data = await api("/runtime/status");
    renderRuntimeStatus(data);
    return data;
  } catch (err) {
    renderRuntimeDisconnected(err);
    return null;
  }
}

function buildSummaryCards(data) {
  const scheduler = data.scheduler || {};
  const worker = data.worker || data.workers?.[0] || {};
  return [
    statHTML(data.application_version || "n/a", "Application Version"),
    statHTML(data.git_commit || "unavailable", "Git Commit"),
    statHTML(data.schema_version ?? "n/a", "Schema Version"),
    statHTML(data.db_path_category || "n/a", "Database Path Category"),
    statHTML(scheduler.owner_id || "unassigned", "Scheduler Leader"),
    statHTML(worker.heartbeat_at ? fmtDate(worker.heartbeat_at) : "no heartbeat", "Worker Heartbeat"),
  ].join("");
}

function renderOverview(data) {
  overviewData = data;
  const sourceCounts = data.source_counts || {};
  const attentionCount = (data.actions_requiring_intervention || []).length;
  if ($("overviewSummaryLine")) {
    const summaryBits = [
      data.runtime_health?.quick_check === "ok" ? "Runtime healthy" : `Runtime ${data.runtime_health?.quick_check || "unknown"}`,
      `${sourceCounts.healthy ?? 0} healthy source${(sourceCounts.healthy ?? 0) === 1 ? "" : "s"}`,
      `${sourceCounts.failed ?? 0} failed`,
      `${data.jobs_pending ?? 0} pending job${(data.jobs_pending ?? 0) === 1 ? "" : "s"}`,
      attentionCount ? `${attentionCount} attention item${attentionCount === 1 ? "" : "s"}` : "no attention items",
    ];
    $("overviewSummaryLine").textContent = summaryBits.join(" · ");
  }
  const systemMetrics = [
    statHTML(data.runtime_health?.quick_check || "n/a", "Runtime Health"),
    statHTML(data.application_version || "n/a", "Build Version"),
    statHTML(data.scheduler?.owner_id || "unassigned", "Scheduler Leader"),
    statHTML(data.worker?.heartbeat_at ? fmtDate(data.worker.heartbeat_at) : "n/a", "Worker Heartbeat"),
  ];
  const flowMetrics = [
    statHTML(sourceCounts.active ?? 0, "Active Sources"),
    statHTML(sourceCounts.healthy ?? 0, "Healthy"),
    statHTML(sourceCounts.retrying ?? 0, "Retrying"),
    statHTML(sourceCounts.stale ?? 0, "Stale"),
    statHTML(sourceCounts.failed ?? 0, "Failed"),
    statHTML(sourceCounts.dead_letter ?? 0, "Dead Letter"),
  ];
  const workloadMetrics = [
    statHTML(data.evidence_captured_today ?? 0, "Evidence Today"),
    statHTML(`${data.jobs_pending ?? 0} / ${data.jobs_running ?? 0}`, "Jobs Pending / Running"),
    statHTML(data.latest_evidence_at ? fmtDate(data.latest_evidence_at) : "n/a", "Latest Evidence"),
    statHTML(data.schema_version ?? "n/a", "Schema"),
  ];
  $("overviewStats").innerHTML = [
    statGroupHTML("System", systemMetrics, "Connection and build posture."),
    statGroupHTML("Signal Flow", flowMetrics, "Source health and queue state."),
    statGroupHTML("Workload", workloadMetrics, "What was captured and when."),
  ].join("");

  const intervention = data.actions_requiring_intervention || [];
  $("overviewIntervention").innerHTML = intervention.length
    ? intervention.map(item => `
      <div class="item">
        <h3>${esc(item.name)}</h3>
        <div class="meta"><span class="tag">${esc(item.status)}</span></div>
        <p class="muted">${esc(item.message || "")}</p>
        ${kvHTML("Next Retry", item.next_retry_at || "")}
      </div>
    `).join("")
    : `<div class="item"><h3>No active intervention</h3><p class="muted">All sources are either healthy, never run, or not yet due for retry.</p></div>`;

  $("overviewUnavailable").innerHTML = (data.unavailable || []).map(item => `
    <div class="item">
      <h3>${esc(item.message)}</h3>
      <p class="muted">${esc(item.key)}</p>
    </div>
  `).join("");

  const failure = data.latest_failure;
  $("overviewLatestFailure").innerHTML = failure
    ? `<div class="item">
        <h3>${esc(failure.source_id || failure.id || "Latest failure")}</h3>
        <div class="meta"><span class="tag">${esc(failure.status || "")}</span><span class="tag">${esc(fmtDate(failure.created_at || ""))}</span></div>
        <p class="muted">${esc(failure.message || "")}</p>
      </div>`
    : `<div class="item"><h3>No recent failure</h3><p class="muted">No failed or dead-letter health event is available yet.</p></div>`;
}

function setCaptureConnection(kind, title, detail) {
  const banner = $("captureConnectionBanner");
  if (!banner) return;
  banner.className = `banner banner-${kind}`;
  if ($("captureConnection")) $("captureConnection").textContent = title;
  if ($("captureConnectionDetail")) $("captureConnectionDetail").textContent = detail;
}

function updateCaptureConnectionFromRuntime() {
  if (runtimeStatusData) {
    setCaptureConnection("success", "Connected", `Runtime ${runtimeStatusData.application_version || ""} on ${runtimeStatusData.git_branch || "unknown branch"}.`);
  } else {
    setCaptureConnection("error", "Disconnected", "The capture inbox cannot write until the local server responds.");
  }
}

function processedSignalHTML(signal) {
  if (!signal) return "";
  const libraryEntryId = signal.metadata?.library_entry_id || "";
  return `<div class="item action-card processed-signal-card" data-signal-route="${esc(signal.route || "")}">
    <h3>${esc(signal.signal || "Processed Signal")}</h3>
    <div class="meta">
      <span class="tag">${esc(signal.route || "")}</span>
      <span class="tag">${esc(signal.signal_type || "")}</span>
      <span class="tag">${esc(signal.confidence || "Medium")}</span>
    </div>
    <p class="muted">${esc(signal.interpretation || "")}</p>
    ${kvHTML("Entity", signal.entity || "")}
    ${kvHTML("Returned Action", signal.returned_action || "")}
    ${kvHTML("First Step", signal.first_step || "")}
    ${kvHTML("Tracking Metric", signal.tracking_metric || "")}
    ${kvHTML("Resurface When", signal.resurfacing_trigger || "")}
    ${kvHTML("Signal ID", signal.id || "")}
    ${kvHTML("Library Entry", libraryEntryId)}
  </div>`;
}

function contextLibraryEntryHTML(entry) {
  const meta = entry.metadata || {};
  return `<div class="item action-card context-library-card" data-library-entry="${esc(entry.id || "")}">
    <h3>${esc(entry.signal || entry.title || "Library Signal")}</h3>
    <div class="meta">
      <span class="tag">${esc(entry.domain || "Other")}</span>
      <span class="tag">${esc(entry.signal_role || "watch")}</span>
      <span class="tag">${esc(entry.actionability || "watch")}</span>
      ${meta.library_route ? `<span class="tag">${esc(meta.library_route)}</span>` : ""}
    </div>
    <p class="muted">${esc(entry.interpretation || "")}</p>
    ${kvHTML("Entity", entry.entity || "")}
    ${kvHTML("Returned Action", entry.returned_action || "")}
    ${kvHTML("Tracking Metric", entry.tracking_metric || "")}
    ${kvHTML("Source", meta.source_name || entry.source_type || "")}
    ${kvHTML("Observation", meta.raw_observation_id || "")}
    ${kvHTML("Entry ID", entry.id || "")}
  </div>`;
}

function observationCardHTML(observation, showActions = true) {
  const signal = observation.latest_signal;
  const raw = observation.raw_input || "";
  return `<div class="item capture-observation-card">
    <h3>${esc(observation.entity || observation.id)}</h3>
    <div class="meta">
      <span class="tag">${esc(observation.processing_status || "queued")}</span>
      <span class="tag">${esc(observation.domain || "Other")}</span>
      <span class="tag">${esc(observation.source_type || "Observation")}</span>
      ${signal ? `<span class="tag">${esc(signal.route || "")}</span>` : ""}
    </div>
    <p class="muted">${esc(raw.slice(0, 220))}</p>
    ${kvHTML("Observation ID", observation.id || "")}
    ${kvHTML("Captured", fmtDate(observation.captured_at || observation.created_at || ""))}
    ${signal ? processedSignalHTML(signal) : ""}
    ${showActions ? `<div class="buttons compact"><button class="secondary small" data-process-observation="${esc(observation.id)}">Process Now</button></div>` : ""}
  </div>`;
}

function renderCaptureSuccess(observation) {
  latestCapturedObservation = observation;
  latestProcessedSignal = observation.latest_signal || null;
  if ($("captureStatus")) {
    $("captureStatus").innerHTML = `<div class="item">
      <h3>Captured</h3>
      <div class="meta">
        <span class="tag">${esc(observation.processing_status || "queued")}</span>
        <span class="tag">${esc(observation.id || "")}</span>
      </div>
      ${kvHTML("Observation ID", observation.id || "")}
      ${kvHTML("Processing Status", observation.processing_status || "")}
      <p class="muted">${esc((observation.raw_input || "").slice(0, 260))}</p>
      <div class="buttons compact">
        <button id="processLatestCaptureBtn" class="secondary small">Process Now</button>
      </div>
    </div>`;
    $("processLatestCaptureBtn")?.addEventListener("click", () => processObservation(observation.id));
  }
  if ($("processedSignalOutput")) {
    $("processedSignalOutput").innerHTML = observation.latest_signal ? processedSignalHTML(observation.latest_signal) : "";
  }
}

function renderCaptureError(message) {
  if ($("captureStatus")) {
    $("captureStatus").innerHTML = `<div class="item error"><h3>Capture Error</h3><p class="muted">${esc(message)}</p></div>`;
  }
}

function capturePayload() {
  return {
    raw_input: $("captureRawInput")?.value ?? "",
    domain: $("captureDomain")?.value ?? "",
    entity: $("captureEntity")?.value ?? "",
    source_type: $("captureSourceType")?.value ?? "Observation",
    urgency: $("captureUrgency")?.value ?? "normal",
    tags: $("captureTags")?.value ?? "",
    source_client: "web-capture",
  };
}

async function captureSignal() {
  const btn = $("captureSignalBtn");
  const payload = capturePayload();
  if (!payload.raw_input.trim()) {
    renderCaptureError("Raw note is required.");
    return;
  }
  try {
    btn.disabled = true;
    if ($("captureStatus")) $("captureStatus").innerHTML = `<div class="item"><h3>Capturing</h3><p class="muted">Writing raw observation and queued processing job...</p></div>`;
    await visibleFeedbackDelay();
    const result = await api("/inbox", { method: "POST", body: JSON.stringify(payload) });
    renderCaptureSuccess(result.observation);
    toast("Captured signal");
    await loadRecentCaptures();
  } catch (err) {
    setCaptureConnection("error", "Disconnected", `Capture failed: ${err.message}`);
    renderCaptureError(err.message);
  } finally {
    btn.disabled = false;
  }
}

async function processObservation(observationId) {
  if (!observationId) return;
  const output = $("processedSignalOutput");
  try {
    if (output) output.innerHTML = `<div class="item"><h3>Processing</h3><p class="muted">Running deterministic signal translation...</p></div>`;
    await visibleFeedbackDelay();
    const result = await api(`/inbox/${encodeURIComponent(observationId)}/process`, { method: "POST", body: JSON.stringify({}) });
    latestCapturedObservation = result.observation;
    latestProcessedSignal = result.processed_signal;
    if (output) output.innerHTML = processedSignalHTML(result.processed_signal);
    renderCaptureSuccess(result.observation);
    toast("Processed signal");
    await loadRecentCaptures();
    await loadContextLibrary();
  } catch (err) {
    if (output) output.innerHTML = `<div class="item error"><h3>Processing Error</h3><p class="muted">${esc(err.message)}</p></div>`;
  }
}

async function loadRecentCaptures() {
  updateCaptureConnectionFromRuntime();
  try {
    const data = await api("/inbox/recent?limit=20");
    const observations = data.observations || [];
    $("recentCaptures").innerHTML = observations.length
      ? observations.map(obs => observationCardHTML(obs)).join("")
      : `<div class="item"><h3>No captures yet</h3><p class="muted">Use Capture Signal to create the first raw observation.</p></div>`;
    await loadContextLibrary();
  } catch (err) {
    setCaptureConnection("error", "Disconnected", `Recent captures failed: ${err.message}`);
    $("recentCaptures").innerHTML = `<div class="item error"><h3>Recent Captures Unavailable</h3><p class="muted">${esc(err.message)}</p></div>`;
  }
}

async function loadContextLibrary() {
  if (!$("contextLibraryList")) return;
  try {
    const data = await api("/context-library?domain=Investing&limit=20");
    const entries = data.entries || [];
    $("contextLibraryStats").innerHTML = [
      statHTML(data.count ?? entries.length, "Investing Entries"),
      statHTML((data.route_counts || []).map(r => `${r.route}:${r.count}`).join(" · ") || "none", "Routes"),
      statHTML((data.domain_counts || []).find(d => d.domain === "Investing")?.count ?? 0, "Total Investing Memory"),
    ].join("");
    $("contextLibraryList").innerHTML = entries.length
      ? entries.map(contextLibraryEntryHTML).join("")
      : `<div class="item"><h3>No Investing Library Entries</h3><p class="muted">Capture and process an Investing signal to promote it into contextual memory.</p></div>`;
  } catch (err) {
    $("contextLibraryStats").innerHTML = "";
    $("contextLibraryList").innerHTML = `<div class="item error"><h3>Library Unavailable</h3><p class="muted">${esc(err.message)}</p></div>`;
  }
}

async function processInvestingQueue() {
  const btn = $("processInvestingQueue");
  try {
    if (btn) btn.disabled = true;
    if ($("contextLibraryStatus")) {
      $("contextLibraryStatus").innerHTML = `<div class="item"><h3>Processing Investing Queue</h3><p class="muted">Promoting queued Investing observations into contextual memory...</p></div>`;
    }
    await visibleFeedbackDelay();
    const result = await api("/inbox/process-queued", {
      method: "POST",
      body: JSON.stringify({ domain: "Investing", limit: 25 }),
    });
    if ($("contextLibraryStatus")) {
      $("contextLibraryStatus").innerHTML = `<div class="item">
        <h3>Investing Queue Processed</h3>
        ${kvHTML("Processed", result.processed_count ?? 0)}
        ${kvHTML("Errors", result.error_count ?? 0)}
      </div>`;
    }
    toast(`Processed ${result.processed_count || 0} Investing capture(s)`);
    await loadRecentCaptures();
    await loadContextLibrary();
  } catch (err) {
    if ($("contextLibraryStatus")) {
      $("contextLibraryStatus").innerHTML = `<div class="item error"><h3>Queue Processing Failed</h3><p class="muted">${esc(err.message)}</p></div>`;
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

function sourceCardHTML(source) {
  const retry = source.retry_state || {};
  const status = source.health_status || source.last_health_status || retry.status || "never_run";
  const details = [
    kvHTML("Schedule", source.poll_interval_minutes ? `${source.poll_interval_minutes} min` : ""),
    kvHTML("Freshness", fmtAge(retry.freshness_age_seconds)),
    kvHTML("Latest Success", retry.latest_success_at || source.last_success_at || ""),
    kvHTML("Next Retry", retry.next_retry_at || ""),
    kvHTML("Latest Run", source.last_run_id || ""),
    kvHTML("Evidence Count", source.evidence_count ?? source.raw_snapshot_count ?? 0),
  ].join("");

  const history = (source.recent_health_events || []).slice(0, 5).map(event => `
    <div class="kv">
      <b>${esc(fmtDate(event.created_at || ""))}</b>
      <span>${esc(event.status || "")}${event.message ? ` — ${esc(event.message)}` : ""}</span>
    </div>
  `).join("");

  const sourceId = source.id || "";
  return `<div class="item">
    <h3>${esc(source.name || sourceId)}</h3>
    <div class="meta">
      <span class="tag">${esc(status)}</span>
      <span class="tag">${esc(source.domain || "Other")}</span>
      <span class="tag">${esc(source.source_type || "")}</span>
    </div>
    <p class="muted">${esc(source.url || source.metadata?.manual_text || "")}</p>
    ${kvHTML("Health", source.health_message || source.current_health?.message || "")}
    ${kvHTML("Latest Success", source.last_success_at || retry.latest_success_at || "")}
    ${kvHTML("Next Retry", retry.next_retry_at || "")}
    ${kvHTML("Current Attempt", retry.status === "retrying" ? `${retry.attempts || 0} / ${retry.max_attempts || 0}` : "")}
    ${kvHTML("Last Failure", retry.last_failure_at || source.last_error_at || "")}
    ${kvHTML("Last Error", retry.last_error || source.last_error || "")}
    ${kvHTML("Freshness", fmtAge(retry.freshness_age_seconds))}
    <div class="buttons compact">
      <button class="secondary small" data-run-source="${esc(sourceId)}">Run Pull</button>
      <button class="ghost small" data-open-source-evidence="${esc(sourceId)}">Open Evidence</button>
    </div>
    <details class="item" style="margin-top:12px">
      <summary>Diagnostics</summary>
      <div class="kv-grid" style="margin-top:10px">
        ${kvHTML("Source ID", source.id || "")}
        ${kvHTML("Job ID", source.last_job_id || "")}
        ${kvHTML("Run ID", source.last_run_id || "")}
        ${kvHTML("Snapshot ID", source.last_snapshot_id || "")}
        ${kvHTML("Pending Jobs", source.pending_job_count ?? 0)}
        ${kvHTML("Claim ID", source.current_claim_id || source.latest_job?.claim_id || "")}
        ${kvHTML("Health Event IDs", (source.recent_health_events || []).map(event => event.id).join(" | "))}
      </div>
      <div class="list" style="margin-top:12px">${history || `<div class="item"><h3>No health history</h3><p class="muted">No health events recorded yet.</p></div>`}</div>
    </details>
  </div>`;
}

function sourcePayload() {
  return {
    name: $("sourceNameInput")?.value || "",
    source_type: $("sourceTypeInput")?.value || "manual",
    poll_interval_minutes: Number($("sourceCadenceInput")?.value || 1),
    domain: $("sourceDomainInput")?.value || "Other",
    entity: $("sourceEntityInput")?.value || "",
    url: $("sourceUrlInput")?.value || "",
    manual_text: $("sourceManualTextInput")?.value || "",
    active: true,
  };
}

function renderSourceCreateStatus(kind, title, detail, extra = "") {
  const el = $("sourceCreateStatus");
  if (!el) return;
  const cls = kind === "error" ? "item error" : "item";
  el.innerHTML = `<div class="${cls}">
    <h3>${esc(title)}</h3>
    <p class="muted">${esc(detail || "")}</p>
    ${extra}
  </div>`;
}

async function createSourceFromUI() {
  const btn = $("createSourceBtn");
  const payload = sourcePayload();
  if (!payload.name.trim()) {
    renderSourceCreateStatus("error", "Source Error", "Source name is required.");
    return;
  }
  if (payload.source_type === "manual" && !payload.manual_text.trim()) {
    renderSourceCreateStatus("error", "Source Error", "Manual source text is required for Manual Text sources.");
    return;
  }
  if (["rss", "url"].includes(payload.source_type) && !payload.url.trim()) {
    renderSourceCreateStatus("error", "Source Error", "URL is required for RSS and URL sources.");
    return;
  }
  try {
    btn.disabled = true;
    renderSourceCreateStatus("info", "Creating Source", "Registering source and initializing never-run health state...");
    await visibleFeedbackDelay();
    const result = await api("/ingest/sources", { method: "POST", body: JSON.stringify(payload) });
    const source = result.source || {};
    latestCreatedSourceId = source.id || "";
    $("runLatestSourceBtn").disabled = !latestCreatedSourceId;
    renderSourceCreateStatus("success", "Source Created", "Run Pull to collect evidence into the inbox.", kvHTML("Source ID", latestCreatedSourceId));
    toast("Source created");
    await loadSources();
  } catch (err) {
    renderSourceCreateStatus("error", "Create Source Failed", err.message);
  } finally {
    btn.disabled = false;
  }
}

async function runSourcePull(sourceId) {
  const id = sourceId || latestCreatedSourceId;
  if (!id) {
    renderSourceCreateStatus("error", "Run Pull Failed", "Create or select a source first.");
    return;
  }
  const runLatest = $("runLatestSourceBtn");
  try {
    if (runLatest) runLatest.disabled = true;
    renderSourceCreateStatus("info", "Running Pull", "Worker is pulling the source, saving a raw snapshot, and creating an inbox observation...");
    await visibleFeedbackDelay();
    const result = await api("/ingest/run", { method: "POST", body: JSON.stringify({ source_id: id }) });
    const firstJob = (result.jobs || [])[0] || {};
    const firstRun = (result.runs || [])[0] || {};
    const firstSnapshot = (result.snapshots || [])[0] || {};
    const firstObservation = (result.observations || [])[0] || {};
    renderSourceCreateStatus("success", "Pull Completed", `${result.created_observations || 0} inbox observation(s), ${result.snapshots?.length || 0} snapshot(s), ${result.skipped || 0} duplicate(s).`, `
      ${kvHTML("Job ID", firstJob.id || "")}
      ${kvHTML("Run ID", firstRun.id || "")}
      ${kvHTML("Snapshot ID", firstSnapshot.id || "")}
      ${kvHTML("Observation ID", firstObservation.observation_id || "")}
    `);
    toast("Pull completed");
    await Promise.all([loadSources(), loadEvidence(), loadRecentCaptures()]);
  } catch (err) {
    renderSourceCreateStatus("error", "Run Pull Failed", err.message);
  } finally {
    if (runLatest) runLatest.disabled = !latestCreatedSourceId;
  }
}

async function loadSources() {
  sourcesData = await api("/sources");
  const sources = sourcesData.sources || [];
  const summary = sourcesData.summary || {};
  $("sourcesSummary").innerHTML = [
    statHTML(summary.active ?? 0, "Active"),
    statHTML(summary.healthy ?? 0, "Healthy"),
    statHTML(summary.retrying ?? 0, "Retrying"),
    statHTML(summary.stale ?? 0, "Stale"),
    statHTML(summary.failed ?? 0, "Failed"),
    statHTML(summary.dead_letter ?? 0, "Dead Letter"),
  ].join("");
  $("sourcesList").innerHTML = sources.length
    ? sources.map(sourceCardHTML).join("")
    : `<div class="card"><div class="item"><h3>No sources yet</h3><p class="muted">Create sources through the data plane API. No sample data is seeded in this shell.</p></div></div>`;
}

function evidenceCardHTML(snapshot, index) {
  return `<div class="item">
    <h3>${esc(snapshot.source_name || snapshot.source_id || snapshot.snapshot_id)}</h3>
    <div class="meta">
      <span class="tag">${esc(snapshot.immutable_status || "")}</span>
      <span class="tag">${esc(snapshot.snapshot_id || snapshot.id || "")}</span>
      <span class="tag">${esc(fmtDate(snapshot.captured_time || snapshot.created_at || ""))}</span>
    </div>
    <p class="muted">${esc((snapshot.raw_payload || "").slice(0, 140))}</p>
    ${kvHTML("Payload Hash", snapshot.payload_hash || "")}
    ${kvHTML("Content Type", snapshot.content_type || "")}
    ${kvHTML("Evidence URL", snapshot.evidence_url || "")}
    <div class="buttons compact">
      <button class="ghost small" data-select-evidence="${esc(index)}">Inspect Raw</button>
    </div>
  </div>`;
}

function renderEvidenceDetail(snapshot) {
  if (!snapshot) {
    $("evidenceDetail").innerHTML = `<div class="item"><h3>No snapshot selected</h3><p class="muted">Select a snapshot to inspect the raw payload.</p></div>`;
    return;
  }
  $("evidenceDetail").innerHTML = `
    <div class="item">
      <h3>${esc(snapshot.snapshot_id || snapshot.id || "")}</h3>
      <div class="meta">
        <span class="tag">${esc(snapshot.immutable_status || "")}</span>
        <span class="tag">${esc(snapshot.source_name || snapshot.source_id || "")}</span>
      </div>
      ${kvHTML("Captured Time", fmtDate(snapshot.captured_time || snapshot.created_at || ""))}
      ${kvHTML("Payload Hash", snapshot.payload_hash || "")}
      ${kvHTML("Evidence URL", snapshot.evidence_url || "")}
      <pre style="white-space:pre-wrap;word-break:break-word;margin:12px 0 0;background:rgba(255,255,255,.04);border:1px solid rgba(79,209,197,.14);border-radius:14px;padding:12px;color:inherit">${esc(snapshot.raw_payload || "")}</pre>
    </div>
  `;
}

function selectEvidence(index) {
  if (!evidenceData?.snapshots?.length) return;
  const snapshot = evidenceData.snapshots[index];
  if (snapshot) renderEvidenceDetail(snapshot);
}

async function loadEvidence() {
  evidenceData = await api("/evidence?limit=100");
  const snapshots = evidenceData.snapshots || [];
  $("evidenceSummary").innerHTML = [
    statHTML(evidenceData.count ?? snapshots.length ?? 0, "Snapshots"),
    statHTML(snapshots[0]?.source_name || "n/a", "Latest Source"),
    statHTML(snapshots[0]?.payload_hash || "n/a", "Latest Payload Hash"),
    statHTML(snapshots[0]?.content_type || "n/a", "Latest Content Type"),
  ].join("");
  $("evidenceList").innerHTML = snapshots.length
    ? snapshots.map((snapshot, index) => evidenceCardHTML(snapshot, index)).join("")
    : `<div class="card"><div class="item"><h3>No evidence yet</h3><p class="muted">Snapshots appear here once a source has been ingested.</p></div></div>`;
  renderEvidenceDetail(snapshots[0] || null);
}

async function loadSystemHealth() {
  const [build, healthEvents] = await Promise.all([
    api("/build-info"),
    api("/data-plane/health-events"),
  ]);
  healthData = build;
  healthData.health_events = healthEvents.health_events || [];
  const scheduler = healthData.scheduler || {};
  const worker = healthData.worker || healthData.workers?.[0] || {};
  $("systemHealthStats").innerHTML = [
    statHTML(healthData.runtime_health?.quick_check || "n/a", "SQLite Quick Check"),
    statHTML(scheduler.owner_id || "unassigned", "Scheduler Leader"),
    statHTML(scheduler.lease_until || "n/a", "Lease Expires"),
    statHTML(worker.status || "n/a", "Worker Status"),
    statHTML(worker.heartbeat_at ? fmtDate(worker.heartbeat_at) : "n/a", "Worker Heartbeat"),
    statHTML(healthData.jobs_pending ?? 0, "Jobs Pending"),
  ].join("");
  $("schedulerPanel").innerHTML = scheduler.owner_id
    ? `<div class="item">
        <h3>${esc(scheduler.owner_id)}</h3>
        <div class="meta"><span class="tag">${scheduler.is_leader ? "leader" : "follower"}</span></div>
        ${kvHTML("Lease Until", scheduler.lease_until || "")}
        ${kvHTML("Heartbeat", scheduler.heartbeat_at || "")}
      </div>`
    : `<div class="item"><h3>No scheduler lease</h3><p class="muted">The scheduler has not acquired leadership yet.</p></div>`;
  $("workerPanel").innerHTML = worker.worker_id
    ? `<div class="item">
        <h3>${esc(worker.worker_id)}</h3>
        <div class="meta"><span class="tag">${esc(worker.status || "")}</span></div>
        ${kvHTML("Heartbeat", worker.heartbeat_at || "")}
        ${kvHTML("Current Job", worker.current_job_id || "")}
        ${kvHTML("Current Claim", worker.current_claim_id || "")}
      </div>`
    : `<div class="item"><h3>No worker heartbeat</h3><p class="muted">Start the worker loop to publish heartbeat truth.</p></div>`;
  const recentEvents = (healthData.health_events || []).map(event => `
    <div class="item">
      <h3>${esc(event.reason || event.id || "")}</h3>
      <div class="meta">
        <span class="tag">${esc(event.status || "")}</span>
        <span class="tag">${esc(fmtDate(event.created_at || ""))}</span>
      </div>
      <details>
        <summary>Diagnostics</summary>
        <div class="kv-grid" style="margin-top:10px">
          ${kvHTML("Event ID", event.id || "")}
          ${kvHTML("Source ID", event.source_id || "")}
          ${kvHTML("Job ID", event.job_id || "")}
          ${kvHTML("Run ID", event.run_id || "")}
          ${kvHTML("Failure Count", event.failure_count ?? 0)}
        </div>
      </details>
      ${kvHTML("Message", event.message || "")}
    </div>
  `).join("");
  $("healthEventsList").innerHTML = recentEvents || `<div class="item"><h3>No scheduler events</h3><p class="muted">Leadership handoff events will appear here.</p></div>`;
}

function jobsCardHTML(job) {
  return `<div class="item">
    <h3>${esc(job.id || "")}</h3>
    <div class="meta">
      <span class="tag">${esc(job.status || "")}</span>
      <span class="tag">${esc(job.source_id || "")}</span>
      <span class="tag">${esc(job.worker_id || "unclaimed")}</span>
    </div>
    ${kvHTML("Claim ID", job.claim_id || job.claimed_by || "")}
    ${kvHTML("Claimed At", fmtDate(job.claimed_at || ""))}
    ${kvHTML("Claim Expires", job.claim_expires_at || "")}
    ${kvHTML("Recovered At", job.recovered_at || "")}
    ${kvHTML("Recovery Count", job.recovery_count ?? 0)}
    ${kvHTML("Previous Worker", job.previous_worker_id || "")}
    ${kvHTML("Recovery Reason", job.recovery_reason || "")}
  </div>`;
}

async function loadJobsRuns() {
  jobsRunsData = await api("/jobs-runs");
  const jobs = jobsRunsData.jobs || [];
  const runs = jobsRunsData.runs || [];
  const claims = jobsRunsData.claims || [];
  const workers = jobsRunsData.workers || [];
  $("jobsRunsStats").innerHTML = [
    statHTML(jobs.length, "Jobs"),
    statHTML(runs.length, "Runs"),
    statHTML(claims.length, "Claims"),
    statHTML(workers.length, "Workers"),
    statHTML(jobsRunsData.scheduler?.owner_id || "unassigned", "Leader"),
    statHTML(jobsRunsData.scheduler?.lease_until || "n/a", "Lease Until"),
  ].join("");
  $("jobsList").innerHTML = jobs.length
    ? jobs.map(jobsCardHTML).join("")
    : `<div class="item"><h3>No jobs</h3><p class="muted">Jobs appear when sources are scheduled or ingested.</p></div>`;
  $("runsList").innerHTML = runs.length
    ? runs.map(run => `<div class="item">
        <h3>${esc(run.id || "")}</h3>
        <div class="meta"><span class="tag">${esc(run.status || "")}</span><span class="tag">${esc(run.source_id || "")}</span></div>
        ${kvHTML("Started", fmtDate(run.started_at || run.created_at || ""))}
        ${kvHTML("Finished", fmtDate(run.finished_at || ""))}
        ${kvHTML("Created Items", run.created_items ?? 0)}
        ${kvHTML("Created Snapshots", run.created_snapshots ?? 0)}
        ${kvHTML("Skipped Items", run.skipped_items ?? 0)}
        ${kvHTML("Error", run.error || "")}
      </div>`).join("")
    : `<div class="item"><h3>No runs</h3><p class="muted">Ingest runs appear after worker execution.</p></div>`;
  $("claimsList").innerHTML = claims.length
    ? claims.map(claim => `<div class="item">
        <h3>${esc(claim.id || "")}</h3>
        <div class="meta"><span class="tag">${esc(claim.status || "")}</span><span class="tag">${esc(claim.worker_id || "")}</span></div>
        ${kvHTML("Job ID", claim.job_id || "")}
        ${kvHTML("Claimed At", fmtDate(claim.claimed_at || ""))}
        ${kvHTML("Lease Until", claim.lease_until || "")}
        ${kvHTML("Recovered At", claim.recovered_at || "")}
        ${kvHTML("Recovery Reason", claim.recovery_reason || "")}
      </div>`).join("")
    : `<div class="item"><h3>No claims</h3><p class="muted">Claim records appear during worker handoff and recovery.</p></div>`;
  $("workersList").innerHTML = workers.length
    ? workers.map(worker => `<div class="item">
        <h3>${esc(worker.worker_id || "")}</h3>
        <div class="meta"><span class="tag">${esc(worker.status || "")}</span><span class="tag">${esc(fmtDate(worker.heartbeat_at || ""))}</span></div>
        ${kvHTML("Current Job", worker.current_job_id || "")}
        ${kvHTML("Current Claim", worker.current_claim_id || "")}
      </div>`).join("")
    : `<div class="item"><h3>No worker heartbeats</h3><p class="muted">Worker liveness is reported here when the runtime is running.</p></div>`;
}

function registryCardHTML(feature) {
  return `<div class="item">
    <h3>${esc(feature.display_name || feature.feature_key || "")}</h3>
    <div class="meta">
      <span class="tag">${esc(feature.lifecycle_status || "")}</span>
      <span class="tag">${esc(feature.architecture || "")}</span>
      <span class="tag">${esc(feature.user_visible ? "visible" : "hidden")}</span>
    </div>
    ${kvHTML("Replacement", feature.replacement_feature || "")}
    ${kvHTML("Data Source", feature.data_source || "")}
    ${kvHTML("Deprecated At", feature.deprecated_at || "")}
    ${kvHTML("Notes", feature.notes || "")}
  </div>`;
}

async function loadBuildInformation() {
  buildInfo = buildInfo || await api("/build-info");
  const data = buildInfo;
  const manifest = data.manifest || {};
  const scheduler = data.scheduler || {};
  const worker = data.worker || data.workers?.[0] || {};
  $("buildInfoStats").innerHTML = buildSummaryCards(data);
  $("featureRegistry").innerHTML = (data.feature_registry?.features || []).length
    ? data.feature_registry.features.map(registryCardHTML).join("")
    : `<div class="item"><h3>No registry entries</h3><p class="muted">Feature registry data was not returned by the server.</p></div>`;
  $("buildManifest").innerHTML = `
    <div class="item">
      <h3>Manifest</h3>
      ${kvHTML("Generated", fmtDate(manifest.generated_at || data.manifest?.generated_at || ""))}
      ${kvHTML("DB Path Category", data.db_path_category || "")}
      ${kvHTML("Scheduler Leader", scheduler.owner_id || "")}
      ${kvHTML("Worker Heartbeat", worker.heartbeat_at ? fmtDate(worker.heartbeat_at) : "")}
    </div>
  `;
}

function legacyCardHTML(data) {
  return `<div class="item">
    <h3>${esc(data.archive_path || "Legacy Archive")}</h3>
    <div class="meta">
      <span class="tag">${esc(data.connection_status || "")}</span>
      <span class="tag">${data.read_only ? "read-only" : "writable"}</span>
      <span class="tag">${esc(data.schema_version ?? "n/a")}</span>
    </div>
    ${kvHTML("Table Count", data.table_counts ?? 0)}
    ${kvHTML("Absolute Path", data.archive_path || "")}
  </div>`;
}

async function loadLegacyArchive() {
  legacyData = await api("/legacy-archive");
  const inventory = legacyData.inventory || {};
  const counts = inventory.row_counts || {};
  const entries = Object.entries(counts).sort((a, b) => String(a[0]).localeCompare(String(b[0])));
  $("legacyArchiveStats").innerHTML = [
    statHTML(legacyData.connection_status || "missing", "Connection"),
    statHTML(legacyData.read_only ? "yes" : "no", "Read Only"),
    statHTML(legacyData.table_counts ?? 0, "Tables"),
    statHTML(legacyData.schema_version ?? "n/a", "Schema Version"),
  ].join("");
  $("legacyArchiveStatus").innerHTML = legacyCardHTML(legacyData);
  $("legacyArchiveCounts").innerHTML = entries.length
    ? entries.map(([table, count]) => `<div class="item"><h3>${esc(table)}</h3><p class="muted">${esc(count)} records</p></div>`).join("")
    : `<div class="item"><h3>No historical tables</h3><p class="muted">Legacy archive data has not been copied into the archive path yet.</p></div>`;
}

function stockSourceLinksHTML(sourceLinks = {}) {
  const links = [];
  if (sourceLinks.yahoo_chart) {
    links.push(`<a href="${esc(sourceLinks.yahoo_chart)}" target="_blank" rel="noreferrer">Chart</a>`);
  }
  if (sourceLinks.yahoo_news) {
    links.push(`<a href="${esc(sourceLinks.yahoo_news)}" target="_blank" rel="noreferrer">News</a>`);
  }
  if (sourceLinks.sec_companyfacts) {
    links.push(`<a href="${esc(sourceLinks.sec_companyfacts)}" target="_blank" rel="noreferrer">SEC</a>`);
  }
  return links.length ? links.join(" · ") : "n/a";
}

function stockWatchlistHTML(items = []) {
  return items.length
    ? items.map(item => `
      <div class="stock-watchlist-item">
        <div>
          <strong>${esc(item.symbol || "")}</strong>
          <span>${esc(item.company || item.symbol || "")}</span>
        </div>
        <button class="ghost small" data-remove-stock="${esc(item.symbol || "")}">Remove</button>
      </div>
    `).join("")
    : `<div class="item empty-state"><h3>Empty watchlist</h3><p class="muted">Add a ticker to load the latest available market snapshot. Default watchlist: AAPL, NVDA, MSFT.</p></div>`;
}

function stockActionSummaryHTML(card) {
  const signalText = (card.signals || []).join(" · ");
  return `<div class="item">
    <h3>${esc(card.symbol || "")} ${esc(card.company || "")}</h3>
    <div class="meta">
      <span class="tag">${esc(card.signal_label || "Needs review")}</span>
      <span class="tag">${esc(card.freshness_state || "")}</span>
      <span class="tag">${esc(card.review_state || "")}</span>
      <span class="tag">${esc(fmtMoney(card.price, card.currency))}</span>
      <span class="tag">${esc(fmtPct(card.one_year_return))}</span>
    </div>
    <p class="muted">${esc(card.decision_reason || "")}</p>
    ${kvHTML("Next step", card.next_step || "")}
    ${kvHTML("Memory Matches", card.memory_matches ?? 0)}
    ${kvHTML("Signals", signalText || "")}
  </div>`;
}

function stockLiveCardHTML(card) {
  const signalText = (card.signals || []).join(" · ");
  const statusClass = (card.freshness_state || "").toLowerCase().includes("error") ? "error" : "";
  const evidence = (card.evidence_bullets || []).map(line => `<li>${esc(line)}</li>`).join("");
  return `<div class="item ${statusClass} stock-snapshot-card" data-snapshot-id="${esc(card.snapshot_id || "")}">
    <div class="stock-card-head">
      <div>
        <h3>${esc(card.symbol || "")} ${esc(card.company || "")}</h3>
        <div class="meta">
          <span class="tag">${esc(card.signal_label || "Needs review")}</span>
          <span class="tag">${esc(card.freshness_state || "Needs review")}</span>
          <span class="tag">${esc(card.review_state || "Needs review")}</span>
          <span class="tag">${esc(fmtMoney(card.price, card.currency))}</span>
          <span class="tag">${esc(fmtPct(card.one_year_return))}</span>
          <span class="tag">${esc(card.news_count ?? 0)} headlines</span>
        </div>
      </div>
      <div class="stock-card-time">
        <span>Fetched at ${esc(fmtDate(card.fetched_at || card.generated_at || ""))}</span>
        <span>Provider timestamp ${esc(card.provider_timestamp ? fmtDate(card.provider_timestamp) : "n/a")}</span>
      </div>
    </div>
    ${kvHTML("Provider", card.provider || "")}
    ${kvHTML("Comparison baseline", card.comparison_baseline || "")}
    ${kvHTML("Next step", card.next_step || "")}
    <div class="item-sublist">
      <b>Evidence</b>
      ${evidence ? `<ul>${evidence}</ul>` : `<p class="muted">No evidence bullets available.</p>`}
    </div>
    ${kvHTML("Signal Mix", signalText || "")}
    <div class="kv"><b>Sources</b><span>${stockSourceLinksHTML(card.source_links || {})}</span></div>
    ${kvHTML("Memory Matches", card.memory_matches ?? 0)}
    ${kvHTML("Snapshot ID", card.snapshot_id || "")}
    <div class="buttons compact">
      <button class="secondary small" data-stock-save-mode="draft" data-snapshot-id="${esc(card.snapshot_id || "")}">Save Draft</button>
      <button class="ghost small" data-stock-save-mode="review" data-snapshot-id="${esc(card.snapshot_id || "")}">Send to Human Review</button>
    </div>
  </div>`;
}

function renderStockIntel(data) {
  const cards = data.cards || [];
  stockIntelData = data;
  if ($("stockLiveBanner")) {
    const bannerKind = data.empty_watchlist ? "banner-info" : data.error_count && !cards.length ? "banner-error" : "banner-success";
    $("stockLiveBanner").className = `banner ${bannerKind}`;
    if ($("stockLiveStatus")) $("stockLiveStatus").textContent = data.snapshot_label || data.snapshot_name || "Latest Available Market Snapshot";
    if ($("stockLiveSummary")) $("stockLiveSummary").textContent = data.summary_line || data.source_summary || "Latest available market snapshot loaded.";
  }
  if ($("stockIntelStats")) {
    const actionCounts = data.action_counts || {};
    const freshnessCounts = cards.reduce((acc, card) => {
      const key = card.freshness_state || "Needs review";
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});
    $("stockIntelStats").innerHTML = [
      statHTML(data.count ?? cards.length, "Snapshots"),
      statHTML(freshnessCounts["Fresh snapshot"] ?? 0, "Fresh snapshot"),
      statHTML(freshnessCounts["Stale snapshot"] ?? 0, "Stale snapshot"),
      statHTML(data.error_count ?? 0, "Errors"),
      statHTML(actionCounts["Research candidate"] ?? 0, "Research candidate"),
      statHTML(actionCounts["Risk flag"] ?? 0, "Risk flag"),
      statHTML(data.generated_at ? fmtDate(data.generated_at) : "n/a", "Fetched at"),
    ].join("");
  }
  if ($("stockWatchlist")) {
    $("stockWatchlist").innerHTML = stockWatchlistHTML(data.watchlist || []);
    document.querySelectorAll("[data-remove-stock]").forEach(button => {
      button.addEventListener("click", () => {
        const next = stockWatchlist.filter(symbol => symbol !== button.dataset.removeStock);
        saveStockWatchlist(next);
        loadStockIntel().catch(() => {});
      });
    });
  }
  if ($("stockActionSummary")) {
    $("stockActionSummary").innerHTML = cards.length
      ? cards.map(stockActionSummaryHTML).join("")
      : `<div class="item empty-state"><h3>No snapshot cards</h3><p class="muted">Refresh the command center to pull the latest available market snapshot.</p></div>`;
  }
  if ($("stockLiveFeed")) {
    $("stockLiveFeed").innerHTML = cards.length
      ? cards.map(stockLiveCardHTML).join("")
      : data.empty_watchlist
        ? `<div class="item empty-state"><h3>Empty watchlist</h3><p class="muted">Add a ticker to load the latest available market snapshot.</p></div>`
        : `<div class="item empty-state"><h3>No snapshot cards</h3><p class="muted">No data returned for the current watchlist.</p></div>`;
  }
  document.querySelectorAll("[data-stock-save-mode]").forEach(button => {
    button.addEventListener("click", () => {
      const snapshotId = button.dataset.snapshotId || "";
      const mode = button.dataset.stockSaveMode || "draft";
      const card = (stockIntelData?.cards || []).find(item => item.snapshot_id === snapshotId);
      if (card) saveStockSnapshot(card, mode);
    });
  });
}

function loadStockWatchlist() {
  try {
    const stored = localStorage.getItem(STOCK_WATCHLIST_KEY);
    if (stored === null) return DEFAULT_STOCK_WATCHLIST.slice();
    const raw = JSON.parse(stored || "[]");
    if (!Array.isArray(raw)) return DEFAULT_STOCK_WATCHLIST.slice();
    const cleaned = raw.map(item => String(item || "").trim().toUpperCase()).filter(Boolean);
    return cleaned.length ? [...new Set(cleaned)] : [];
  } catch (err) {
    return DEFAULT_STOCK_WATCHLIST.slice();
  }
}

function saveStockWatchlist(next) {
  stockWatchlist = [...new Set((next || []).map(item => String(item || "").trim().toUpperCase()).filter(Boolean))];
  try {
    localStorage.setItem(STOCK_WATCHLIST_KEY, JSON.stringify(stockWatchlist));
  } catch (err) {}
}

function currentStockMode() {
  return $("stockSnapshotMode")?.value || "";
}

function setCurrentStockMode(value) {
  if ($("stockSnapshotMode")) $("stockSnapshotMode").value = value || "";
  try {
    localStorage.setItem(STOCK_SNAPSHOT_MODE_KEY, value || "");
  } catch (err) {}
}

function loadStoredStockMode() {
  try {
    return localStorage.getItem(STOCK_SNAPSHOT_MODE_KEY) || "";
  } catch (err) {
    return "";
  }
}

function renderStockSnapshotHistory(data) {
  if (!$("stockSnapshotHistory")) return;
  const snapshots = data.snapshots || [];
  if (!snapshots.length) {
    $("stockSnapshotHistory").innerHTML = `<div class="item empty-state"><h3>No saved snapshots</h3><p class="muted">Save a draft or send a snapshot to Human Review to make it appear here.</p></div>`;
    return;
  }
  $("stockSnapshotHistory").innerHTML = snapshots.map(snapshot => {
    const state = snapshot.review_state || "Needs review";
    const saveMode = snapshot.save_mode || "draft";
    const payload = snapshot.snapshot || {};
    const card = payload.card || {};
    return `<div class="item stock-history-card">
      <h3>${esc(snapshot.symbol || "")} ${esc(snapshot.company || "")}</h3>
      <div class="meta">
        <span class="tag">${esc(saveMode)}</span>
        <span class="tag">${esc(state)}</span>
        <span class="tag">${esc(card.signal_label || snapshot.signal_label || "Needs review")}</span>
      </div>
      ${kvHTML("Fetched at", fmtDate(snapshot.fetched_at || ""))}
      ${kvHTML("Provider timestamp", snapshot.provider_timestamp ? fmtDate(snapshot.provider_timestamp) : "n/a")}
      ${kvHTML("Trusted entry", snapshot.trusted_entry_id || "")}
      ${kvHTML("Human review", snapshot.human_review_id || "")}
      ${kvHTML("Comparison baseline", snapshot.comparison_baseline || "")}
    </div>`;
  }).join("");
}

async function loadStockSnapshotHistory() {
  if (!$("stockSnapshotHistory")) return;
  try {
    const data = await api("/stock/snapshot/history?limit=10");
    renderStockSnapshotHistory(data);
  } catch (err) {
    $("stockSnapshotHistory").innerHTML = `<div class="item error"><h3>History unavailable</h3><p class="muted">${esc(err.message)}</p></div>`;
  }
}

function stockReviewHeaders() {
  return {
    "X-Info-Analyzer-Environment": "active",
  };
}

function renderStockReviewQueue(data) {
  if (!$("stockReviewQueue")) return;
  const reviews = (data.reviews || []).filter(review => (review.subject_type || "") === "stock_snapshot");
  if (!reviews.length) {
    $("stockReviewQueue").innerHTML = `<div class="item empty-state"><h3>No pending stock reviews</h3><p class="muted">Send a snapshot to Human Review to make it appear here.</p></div>`;
    return;
  }
  $("stockReviewQueue").innerHTML = reviews.map(review => `
    <div class="item stock-review-item" data-stock-review-id="${esc(review.id || "")}">
      <h3>${esc(review.subject_id || review.id || "")}</h3>
      <div class="meta">
        <span class="tag">pending</span>
        <span class="tag">${esc(review.subject_type || "")}</span>
        <span class="tag">${esc(review.review_type || "")}</span>
      </div>
      <p class="muted">${esc(review.system_interpretation || "(no system interpretation)")}</p>
      ${kvHTML("System confidence", Number(review.system_confidence || 0).toFixed(2))}
      <label>Correction
        <input data-stock-review-correction="${esc(review.id || "")}" placeholder="Optional correction for Correct" />
      </label>
      <label>Reason
        <textarea data-stock-review-reason="${esc(review.id || "")}" rows="2" placeholder="Optional reason"></textarea>
      </label>
      <div class="buttons compact">
        <button class="secondary small" data-stock-review-verdict="confirm" data-stock-review-id="${esc(review.id || "")}">Confirm</button>
        <button class="secondary small" data-stock-review-verdict="correct" data-stock-review-id="${esc(review.id || "")}">Correct</button>
        <button class="ghost small" data-stock-review-verdict="needs_more_evidence" data-stock-review-id="${esc(review.id || "")}">Needs more evidence</button>
      </div>
    </div>
  `).join("");
  document.querySelectorAll("[data-stock-review-verdict]").forEach(button => {
    button.addEventListener("click", () => submitStockReviewVerdict(button.dataset.stockReviewId || "", button.dataset.stockReviewVerdict || ""));
  });
}

async function loadStockHumanReviews() {
  if (!$("stockReviewQueue")) return;
  try {
    const data = await api("/human-review/pending", { headers: stockReviewHeaders() });
    renderStockReviewQueue(data);
  } catch (err) {
    $("stockReviewQueue").innerHTML = `<div class="item error"><h3>Review queue unavailable</h3><p class="muted">${esc(err.message)}</p></div>`;
  }
}

async function submitStockReviewVerdict(reviewId, verdict) {
  if (!reviewId) return;
  const correction = ($(`[data-stock-review-correction="${reviewId}"]`)?.value || "").trim();
  const reason = ($(`[data-stock-review-reason="${reviewId}"]`)?.value || "").trim();
  try {
    if ($("stockLiveSummary")) $("stockLiveSummary").textContent = verdict === "correct" ? "Submitting correction..." : "Submitting review verdict...";
    const data = await api(`/human-review/${encodeURIComponent(reviewId)}/verdict`, {
      method: "POST",
      headers: stockReviewHeaders(),
      body: JSON.stringify({
        verdict,
        correction: correction || null,
        reason: reason || null,
        confidence: 0.9,
        reviewed_by: "tariye",
      }),
    });
    if (!data.recorded) throw new Error("Review was not recorded");
    await loadStockHumanReviews();
    await loadStockSnapshotHistory();
    await loadStockIntel({ silent: true });
    toast(verdict === "correct" ? "Stock review corrected" : verdict === "confirm" ? "Stock review confirmed" : "Stock review updated");
  } catch (err) {
    toast(`Review failed: ${err.message}`);
  }
}

function stockStatusFromRefresh(previous, nextData) {
  const nextCards = nextData?.cards || [];
  if (nextData?.empty_watchlist) return "Empty watchlist";
  if (!nextCards.length) return "No data returned";
  const previousMap = new Map((previous?.cards || []).map(card => [card.symbol, card.provider_timestamp || ""]));
  const changed = nextCards.some(card => (previousMap.get(card.symbol) || "") !== (card.provider_timestamp || ""));
  return changed ? `Fetched at ${fmtDate(nextData.generated_at || "")}` : "No newer provider data available.";
}

function bindStockCardActions() {
  document.querySelectorAll("[data-stock-save-mode]").forEach(button => {
    button.addEventListener("click", () => {
      const snapshotId = button.dataset.snapshotId || "";
      const mode = button.dataset.stockSaveMode || "draft";
      const card = (stockIntelData?.cards || []).find(item => item.snapshot_id === snapshotId);
      if (card) saveStockSnapshot(card, mode);
    });
  });
}

async function saveStockSnapshot(card, mode) {
  const endpoint = mode === "review" ? "/stock/snapshot/review" : "/stock/snapshot/draft";
  const button = Array.from(document.querySelectorAll(`[data-stock-save-mode="${mode}"]`)).find(item => item.dataset.snapshotId === (card.snapshot_id || ""));
  try {
    if (button) button.disabled = true;
    if ($("stockLiveBanner")) {
      $("stockLiveBanner").className = "banner banner-loading";
      if ($("stockLiveStatus")) $("stockLiveStatus").textContent = mode === "review" ? "Sending to Human Review..." : "Saving draft...";
      if ($("stockLiveSummary")) $("stockLiveSummary").textContent = card.comparison_baseline || "Saving snapshot...";
    }
    const result = await api(endpoint, {
      method: "POST",
      body: JSON.stringify({ card }),
    });
    const saved = result.snapshot || {};
    stockIntelData = {
      ...stockIntelData,
      cards: (stockIntelData?.cards || []).map(item => item.snapshot_id === card.snapshot_id ? { ...item, review_state: saved.review_state || item.review_state, human_review_id: saved.human_review_id || item.human_review_id, save_mode: saved.save_mode || item.save_mode, trusted_entry_id: saved.trusted_entry_id || item.trusted_entry_id } : item),
    };
    renderStockIntel(stockIntelData);
    await loadStockSnapshotHistory();
    await loadStockHumanReviews();
    toast(mode === "review" ? "Sent to Human Review" : "Draft saved");
  } catch (err) {
    toast(`Save failed: ${err.message}`);
    if ($("stockLiveSummary")) $("stockLiveSummary").textContent = err.message;
  } finally {
    if (button) button.disabled = false;
  }
}

function stockManualEvidenceBullets(analysis = {}) {
  const quote = analysis.quote || {};
  const financials = analysis.financials || {};
  const news = analysis.news || [];
  const bullets = [];
  if (quote.price !== undefined && quote.price !== null) {
    bullets.push(`Latest available quote ${fmtMoney(quote.price, quote.currency)}`);
  }
  if (quote.provider_timestamp) {
    bullets.push(`Provider timestamp ${fmtDate(quote.provider_timestamp)}`);
  }
  if (quote.previous_close !== undefined && quote.previous_close !== null) {
    bullets.push(`Previous close ${fmtMoney(quote.previous_close, quote.currency)}`);
  }
  if (financials.latest_quarter?.revenue?.display) {
    bullets.push(`Latest SEC quarter revenue ${financials.latest_quarter.revenue.display}`);
  }
  if (news.length) {
    bullets.push(`Recent Yahoo Finance headlines scanned: ${news.length}`);
  }
  return bullets.slice(0, 4);
}

function startStockIntelAutoRefresh() {
  if (stockIntelTimer) return;
  stockIntelTimer = window.setInterval(() => {
    if ($("stock-intel")?.classList.contains("active")) {
      loadStockIntel({ silent: true }).catch(() => {});
    }
  }, 60000);
}

function stopStockIntelAutoRefresh() {
  if (!stockIntelTimer) return;
  clearInterval(stockIntelTimer);
  stockIntelTimer = null;
}

async function loadStockIntel({ silent = false } = {}) {
  if (!$("stockLiveFeed")) return;
  if (stockIntelLoading) return;
  stockIntelLoading = true;
  if (!stockWatchlist.length) stockWatchlist = loadStockWatchlist();
  const previous = stockIntelData;
  try {
    if ($("stockOutput") && !$("stockOutput").innerHTML.trim()) {
      $("stockOutput").innerHTML = `<div class="item empty-state"><h3>Manual probe ready</h3><p class="muted">Use Analyze to inspect one ticker at a time. This does not save automatically.</p></div>`;
    }
    if ($("stockLiveBanner")) {
      $("stockLiveBanner").className = "banner banner-loading";
      if ($("stockLiveStatus")) $("stockLiveStatus").textContent = "Loading latest available market snapshot...";
      if ($("stockLiveSummary")) $("stockLiveSummary").textContent = "Fetching the latest available quote, filings, and headlines.";
    }
    const mode = $("stockSnapshotMode")?.value || "";
    try {
      localStorage.setItem(STOCK_SNAPSHOT_MODE_KEY, mode);
    } catch (err) {}
    const data = await api("/stock/snapshot", {
      method: "POST",
      body: JSON.stringify({
        symbols: stockWatchlist,
        watchlist: stockWatchlist,
        simulate_state: mode,
      }),
    });
    renderStockIntel(data);
    if ($("stockLiveBanner")) {
      $("stockLiveBanner").className = data.error_count && !data.cards?.length ? "banner banner-error" : "banner banner-success";
      if ($("stockLiveStatus")) $("stockLiveStatus").textContent = data.snapshot_label || "Latest Available Market Snapshot";
      if ($("stockLiveSummary")) {
        const prevMap = new Map((previous?.cards || []).map(card => [card.symbol, card.provider_timestamp || ""]));
        const changed = (data.cards || []).some(card => (prevMap.get(card.symbol) || "") !== (card.provider_timestamp || ""));
        $("stockLiveSummary").textContent = data.empty_watchlist
          ? "Empty watchlist"
          : (changed ? `Fetched at ${fmtDate(data.generated_at || "")}` : "No newer provider data available.");
      }
    }
    await loadStockSnapshotHistory();
    await loadStockHumanReviews();
    if (!silent) {
      toast(data.empty_watchlist ? "Empty watchlist" : "Latest available market snapshot refreshed");
    }
    return data;
  } catch (err) {
    if ($("stockLiveBanner")) {
      $("stockLiveBanner").className = "banner banner-error";
      if ($("stockLiveStatus")) $("stockLiveStatus").textContent = "Snapshot unavailable";
      if ($("stockLiveSummary")) $("stockLiveSummary").textContent = err.message;
    }
    if ($("stockIntelStats")) $("stockIntelStats").innerHTML = "";
    if ($("stockWatchlist")) {
      $("stockWatchlist").innerHTML = `<div class="item error"><h3>Snapshot error</h3><p class="muted">${esc(err.message)}</p></div>`;
    }
    if ($("stockActionSummary")) {
      $("stockActionSummary").innerHTML = `<div class="item error"><h3>Snapshot error</h3><p class="muted">${esc(err.message)}</p></div>`;
    }
    if ($("stockLiveFeed")) {
      $("stockLiveFeed").innerHTML = `<div class="item error"><h3>Snapshot failed</h3><p class="muted">${esc(err.message)}</p></div>`;
    }
    if (!silent) toast(`Snapshot failed: ${err.message}`);
    return null;
  } finally {
    stockIntelLoading = false;
  }
}

function alertSeverityClass(alert) {
  const severity = String(alert?.severity || "watch").toLowerCase();
  if (severity === "critical") return "critical";
  if (severity === "important") return "important";
  if (severity === "info") return "info";
  return "watch";
}

function alertStateLabel(alert) {
  const raw = String(alert?.status || "new").replaceAll("_", " ");
  return raw.replace(/\b\w/g, ch => ch.toUpperCase());
}

function alertEvidenceHTML(alert) {
  const evidence = Array.isArray(alert?.evidence) ? alert.evidence.filter(Boolean) : [];
  if (!evidence.length) return `<p class="muted">No evidence bullets available.</p>`;
  return `<ul class="alert-evidence-list">${evidence.map(item => `<li>${esc(item)}</li>`).join("")}</ul>`;
}

function alertActionButtonText(alert) {
  if (alert?.converted_action_id) return "Converted";
  if (!alert?.can_convert_to_action) return "Review required";
  return "Convert to Action";
}

function alertCardHTML(alert) {
  const isLocal = String(alert?.source || "") === "local_archive";
  const reviewId = alert?.human_review_id || "";
  const convertDisabled = !alert?.can_convert_to_action && !alert?.converted_action_id;
  const snoozeButtons = [15, 60, 240, 1440].map(minutes => `
    <button class="ghost small" data-alert-snooze="${minutes}" data-alert-id="${esc(alert.id || "")}">${minutes >= 1440 ? "1 day" : minutes >= 240 ? "4 hours" : minutes >= 60 ? "1 hour" : "15 minutes"}</button>
  `).join("");
  return `<div class="item alert-card ${esc(alertSeverityClass(alert))}">
    <div class="alert-card-head">
      <div>
        <h3>${esc(alert.title || "Alert")}</h3>
        <div class="meta">
          <span class="tag">${esc(alert.severity || "watch")}</span>
          <span class="tag">${esc(alertStateLabel(alert))}</span>
          <span class="tag">${esc(alert.rule?.name || alert.rule_id || "")}</span>
          ${alert.can_convert_to_action ? `<span class="tag">Eligible</span>` : `<span class="tag">Review required</span>`}
        </div>
      </div>
      <div class="alert-card-meta">
        ${kvHTML("Source", alert.source_label || alert.source || "")}
        ${kvHTML("Entity", alert.entity || "")}
      </div>
    </div>
    <p class="muted">${esc(alert.message || "")}</p>
    ${kvHTML("Why this fired", alert.message || "")}
    ${kvHTML("Triggered at", fmtDate(alert.triggered_at || ""))}
    ${kvHTML("Last checked at", fmtDate(alert.last_checked_at || ""))}
    ${kvHTML("Next step", alert.next_step || "")}
    ${kvHTML("Human Review", reviewId || "Not sent")}
    ${kvHTML("Trusted Entry", alert.trusted_entry_id || "")}
    ${kvHTML("Converted Action", alert.converted_action_id || "")}
    ${isLocal ? kvHTML("Source label", alert.source_label || "") : ""}
    ${isLocal ? kvHTML("Relative path", alert.relative_path || "") : ""}
    ${isLocal ? kvHTML("Broken referenced path", alert.referenced_path || "") : ""}
    <div class="item-sublist">
      <b>Evidence</b>
      ${alertEvidenceHTML(alert)}
    </div>
    <div class="buttons compact">
      <button class="secondary small" data-alert-action="acknowledge" data-alert-id="${esc(alert.id || "")}">Acknowledge</button>
      <button class="secondary small" data-alert-action="dismiss" data-alert-id="${esc(alert.id || "")}">Dismiss</button>
      <button class="secondary small" data-alert-action="send-review" data-alert-id="${esc(alert.id || "")}">Send to Human Review</button>
      <button class="primary small" data-alert-action="convert-action" data-alert-id="${esc(alert.id || "")}" ${convertDisabled ? "disabled" : ""}>${esc(alertActionButtonText(alert))}</button>
    </div>
    <div class="buttons compact alert-snooze-buttons">
      ${snoozeButtons}
    </div>
  </div>`;
}

function renderAlertEngineBanner(data) {
  if (!$("alertEngineBanner")) return;
  const status = String(data?.engine_status || "ready");
  let kind = "info";
  if (status === "degraded") kind = "error";
  else if (status === "no rules") kind = "info";
  else if ((data?.active_alert_count || 0) > 0) kind = "warning";
  else kind = "success";
  $("alertEngineBanner").className = `banner banner-${kind}`;
  if ($("alertEngineStatus")) {
    $("alertEngineStatus").textContent = status === "ready" ? "Alert engine ready" : status === "degraded" ? "Alert engine degraded" : status === "no rules" ? "No alert rules" : "Alerts active";
  }
  if ($("alertEngineSummary")) {
    const parts = [
      `Last checked ${data.last_checked_at ? fmtDate(data.last_checked_at) : "n/a"}`,
      `${data.active_alert_count ?? 0} active alert${(data.active_alert_count ?? 0) === 1 ? "" : "s"}`,
      data.errors?.length ? `${data.errors.length} check error${data.errors.length === 1 ? "" : "s"}` : "No check errors",
    ];
    $("alertEngineSummary").textContent = parts.join(" · ");
  }
  if ($("alertEngineStats")) {
    const counts = data.counts || {};
    $("alertEngineStats").innerHTML = [
      statHTML(data.rules?.length ?? 0, "Rules"),
      statHTML(counts.active ?? 0, "Active"),
      statHTML(counts.resolved ?? 0, "Resolved"),
      statHTML(data.created ?? 0, "Created"),
      statHTML(data.updated ?? 0, "Updated"),
      statHTML(data.errors?.length ?? 0, "Errors"),
    ].join("");
  }
}

function renderLocalSourceStatus(data) {
  if (!$("localSourceBanner")) return;
  const accessible = !!data?.accessible;
  const brokenCount = Number(data?.broken_reference_count || 0);
  let kind = "info";
  if (!accessible) kind = "error";
  else if (brokenCount > 0) kind = "warning";
  else kind = "success";
  $("localSourceBanner").className = `banner banner-${kind}`;
  if ($("localSourceState")) {
    $("localSourceState").textContent = accessible ? "Accessible" : "Unavailable";
  }
  if ($("localSourceSummary")) {
    const parts = [
      `Root ${data?.root || "n/a"}`,
      `${data?.file_count ?? 0} files`,
      `${brokenCount} broken reference${brokenCount === 1 ? "" : "s"}`,
    ];
    $("localSourceSummary").textContent = parts.join(" · ");
  }
  if ($("localSourceStats")) {
    $("localSourceStats").innerHTML = [
      statHTML(accessible ? "accessible" : "unavailable", "Root"),
      statHTML(data?.directory_count ?? 0, "Directories"),
      statHTML(data?.file_count ?? 0, "Files"),
      statHTML(brokenCount, "Broken refs"),
    ].join("");
  }
  if ($("localSourceStatus")) {
    $("localSourceStatus").innerHTML = [
      `<div class="item"><h3>Source root</h3>${kvHTML("Source label", data?.source_label || "")}${kvHTML("Configured root", data?.root || "")}${kvHTML("Accessible", accessible ? "Yes" : "No")}${kvHTML("Approx size", data?.approx_size_bytes ? `${Math.round(Number(data.approx_size_bytes) / (1024 * 1024))} MB` : "n/a")}</div>`,
      `<div class="item"><h3>Read-only inventory</h3>${kvHTML("Directories", data?.directory_count ?? 0)}${kvHTML("Files", data?.file_count ?? 0)}${kvHTML("Inaccessible entries", (data?.inaccessible || []).length)}${kvHTML("Database candidates", (data?.database_candidates || []).length)}</div>`,
      `<div class="item"><h3>Operational truth</h3><p class="muted">This inventory is read-only. Discovered paths are not content-ingested in v0.99.1.</p></div>`,
    ].join("");
  }
  if ($("localSourceDetails")) {
    const broken = data?.broken_reference_samples || [];
    const dbCandidates = (data?.database_candidates || []).slice(0, 5);
    const repoRoots = (data?.repo_roots || []).slice(0, 5);
    $("localSourceDetails").innerHTML = [
      `<div class="item"><h3>Repo roots</h3>${repoRoots.length ? repoRoots.map(item => `<div class="kv"><b>Root</b><span>${esc(item)}</span></div>`).join("") : `<p class="muted">No repository roots discovered.</p>`}</div>`,
      `<div class="item"><h3>Likely databases</h3>${dbCandidates.length ? dbCandidates.map(item => `<div class="kv"><b>${esc(item.relative_path || "")}</b><span>${esc(item.size || 0)} bytes · ${esc(item.modified_at || "")}</span></div>`).join("") : `<p class="muted">No database candidates found.</p>`}</div>`,
      `<div class="item"><h3>Broken references</h3>${broken.length ? broken.map(item => `
        <div class="item mini-item">
          <h3>${esc(item.source_label || "Archive")}</h3>
          ${kvHTML("Relative path", item.relative_path || "")}
          ${kvHTML("Referenced path", item.referenced_path || "")}
          ${kvHTML("Reason", item.reason || "")}
          ${kvHTML("Next step", item.next_step || "")}
        </div>
      `).join("") : `<p class="muted">No broken local references discovered in the configured archive root.</p>`}</div>`,
    ].join("");
  }
}

function renderAlertList(data) {
  if (!$("alertList")) return;
  const alerts = data?.alerts || [];
  if (!alerts.length) {
    $("alertList").innerHTML = `<div class="item empty-state"><h3>No alerts</h3><p class="muted">Run Alert Check or Create Test Alert to generate the first visible alert.</p></div>`;
    return;
  }
  $("alertList").innerHTML = alerts.map(alertCardHTML).join("");
}

async function loadLocalSourceStatus({ silent = false } = {}) {
  if (!$("localSourceBanner")) return null;
  try {
    const data = await api("/local-source/status");
    localSourceData = data;
    renderLocalSourceStatus(data);
    if (!silent) return data;
    return data;
  } catch (err) {
    localSourceData = null;
    if ($("localSourceBanner")) {
      $("localSourceBanner").className = "banner banner-error";
      if ($("localSourceState")) $("localSourceState").textContent = "Unavailable";
      if ($("localSourceSummary")) $("localSourceSummary").textContent = err.message;
    }
    if ($("localSourceStatus")) {
      $("localSourceStatus").innerHTML = `<div class="item error"><h3>Archive inventory failed</h3><p class="muted">${esc(err.message)}</p></div>`;
    }
    if ($("localSourceDetails")) {
      $("localSourceDetails").innerHTML = "";
    }
    return null;
  }
}

async function loadAlerts({ silent = false } = {}) {
  if (!$("alertList")) return null;
  try {
    const data = await api("/alerts");
    alertsData = data;
    alertCheckResult = null;
    renderAlertEngineBanner(data);
    renderAlertList(data);
    if (!silent) {
      await loadLocalSourceStatus({ silent: true });
    }
    return data;
  } catch (err) {
    alertsData = null;
    renderAlertEngineBanner({
      engine_status: "degraded",
      last_checked_at: "",
      active_alert_count: 0,
      errors: [{ error: err.message }],
      counts: {},
      rules: [],
      created: 0,
      updated: 0,
      resolved: 0,
    });
    $("alertList").innerHTML = `<div class="item error"><h3>Alert engine unavailable</h3><p class="muted">${esc(err.message)}</p></div>`;
    return null;
  }
}

async function runAlertCheck() {
  const button = $("runAlertCheck");
  try {
    if (button) button.disabled = true;
    if ($("alertEngineBanner")) {
      $("alertEngineBanner").className = "banner banner-loading";
      if ($("alertEngineStatus")) $("alertEngineStatus").textContent = "Running alert check...";
      if ($("alertEngineSummary")) $("alertEngineSummary").textContent = "Re-evaluating seeded alert rules.";
    }
    await visibleFeedbackDelay();
    const data = await api("/alerts/check", { method: "POST", body: "{}" });
    alertCheckResult = data;
    alertsData = data;
    renderAlertEngineBanner(data);
    renderAlertList(data);
    await loadLocalSourceStatus({ silent: true });
    await loadAlertReviews();
    toast(`Alert check: ${data.created ?? 0} created, ${data.updated ?? 0} updated, ${data.resolved ?? 0} resolved`);
    return data;
  } catch (err) {
    if ($("alertEngineBanner")) {
      $("alertEngineBanner").className = "banner banner-error";
      if ($("alertEngineStatus")) $("alertEngineStatus").textContent = "Alert check failed";
      if ($("alertEngineSummary")) $("alertEngineSummary").textContent = err.message;
    }
    toast(`Alert check failed: ${err.message}`);
    return null;
  } finally {
    if (button) button.disabled = false;
  }
}

async function createTestAlert() {
  const button = $("createTestAlert");
  try {
    if (button) button.disabled = true;
    await visibleFeedbackDelay();
    const data = await api("/alerts/test", { method: "POST", body: JSON.stringify({ note: "TEST ALERT created from the Alert Center." }) });
    await loadAlerts({ silent: true });
    await loadAlertReviews();
    toast(`Created ${data?.event?.title || "TEST ALERT"}`);
    return data;
  } catch (err) {
    toast(`Create test alert failed: ${err.message}`);
    return null;
  } finally {
    if (button) button.disabled = false;
  }
}

async function refreshAlertCenter() {
  await Promise.all([
    loadAlerts(),
    loadLocalSourceStatus(),
  ]);
}

async function performAlertAction(alertId, action, payload = {}) {
  const result = await api(`/alerts/${encodeURIComponent(alertId)}/${action}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  await loadAlerts({ silent: true });
  await loadAlertReviews();
  return result;
}

function alertReviewCardHTML(review) {
  const alert = review.alert_event || {};
  return `<button class="item review-item" data-alert-review-id="${esc(review.id || review.review_id || "")}">
    <h3>${esc(review.alert_title || review.system_interpretation || review.id || "Alert Review")}</h3>
    <div class="meta">
      <span class="tag">pending</span>
      <span class="tag">${esc(review.subject_type || "")}</span>
      <span class="tag">${esc(review.review_type || "")}</span>
    </div>
    <p class="muted">${esc(review.alert_message || review.system_interpretation || "")}</p>
    ${review.alert_source_label ? kvHTML("Source", review.alert_source_label) : ""}
    ${review.alert_relative_path ? kvHTML("Relative path", review.alert_relative_path) : ""}
    ${alert.id ? kvHTML("Alert ID", alert.id) : ""}
  </button>`;
}

function renderAlertReviewDetail(review) {
  if (!$("alertReviewDetailContainer")) return;
  $("alertReviewDetailContainer").style.display = "block";
  const alert = review.alert_event || {};
  $("alertReviewDetail").innerHTML = `
    <div class="review-evidence section">
      <h3>Alert Evidence</h3>
      ${kvHTML("Review", review.id || "")}
      ${kvHTML("Subject", review.subject_id || "")}
      ${kvHTML("Type", review.subject_type || "")}
      ${kvHTML("Alert title", review.alert_title || "")}
      ${kvHTML("Alert message", review.alert_message || "")}
      ${kvHTML("Source", review.alert_source_label || review.alert_source || "")}
      ${kvHTML("Relative path", review.alert_relative_path || "")}
      ${kvHTML("Broken referenced path", review.alert_referenced_path || "")}
      <div class="item-sublist">
        <b>Evidence bullets</b>
        ${alertEvidenceHTML(alert)}
      </div>
    </div>
    <div class="review-proposal section">
      <h3>System Proposal</h3>
      <p class="muted">${esc(review.system_interpretation || review.alert_message || "(system proposal unavailable)")}</p>
      ${kvHTML("System Confidence", Number(review.system_confidence || 0).toFixed(2))}
    </div>
    <div class="review-judgment section">
      <h3>Your Judgment</h3>
      <form id="alertVerdictForm" novalidate>
        <div class="form-group">
          <label>Verdict</label>
          <div id="alertVerdictError" class="field-error"></div>
          <div class="button-group">
            <button type="button" class="verdict-btn" data-alert-verdict="confirm">Confirm</button>
            <button type="button" class="verdict-btn" data-alert-verdict="correct">Correct</button>
            <button type="button" class="verdict-btn" data-alert-verdict="reject">Reject</button>
            <button type="button" class="verdict-btn" data-alert-verdict="needs_more_evidence">Needs More Evidence</button>
          </div>
          <input type="hidden" id="alertVerdictInput" />
        </div>
        <div class="form-group">
          <label>Correction <span id="alertCorrectionRequired" class="required" style="display:none">*</span></label>
          <div id="alertCorrectionError" class="field-error"></div>
          <input id="alertCorrectionInput" placeholder="Enter corrected interpretation" />
        </div>
        <div class="form-group">
          <label>Human Confidence</label>
          <div id="alertConfidenceError" class="field-error"></div>
          <input id="alertConfidenceInput" type="number" min="0" max="1" step="0.01" placeholder="0.75" />
        </div>
        <div class="form-group">
          <label>Reason <span id="alertReasonRequired" class="required" style="display:none">*</span></label>
          <div id="alertReasonError" class="field-error"></div>
          <textarea id="alertReasonInput" placeholder="Required for Reject and Needs More Evidence"></textarea>
        </div>
        <div class="buttons"><button id="alertSubmitBtn" class="primary" type="submit">Save Verdict</button></div>
      </form>
    </div>
  `;
  document.querySelectorAll("[data-alert-verdict]").forEach(button => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-alert-verdict]").forEach(item => item.classList.remove("selected"));
      button.classList.add("selected");
      $("alertVerdictInput").value = button.dataset.alertVerdict;
      $("alertCorrectionRequired").style.display = button.dataset.alertVerdict === "correct" ? "inline" : "none";
      $("alertReasonRequired").style.display = ["reject", "needs_more_evidence"].includes(button.dataset.alertVerdict) ? "inline" : "none";
    });
  });
  $("alertVerdictForm")?.addEventListener("submit", submitAlertReviewVerdict);
}

async function loadAlertReviews() {
  if (!$("alertReviewQueue")) return null;
  if (isLoadingAlertReviews) return null;
  isLoadingAlertReviews = true;
  $("alertReviewQueue").innerHTML = `<div class="item"><p class="muted">Loading alert reviews...</p></div>`;
  try {
    const data = await api("/human-review/pending");
    const reviews = (data.reviews || []).filter(review => String(review.subject_type || "").toLowerCase() === "alert_event");
    if ($("alertReviewSummary")) {
      $("alertReviewSummary").innerHTML = [
        statHTML(reviews.length, "Pending alert reviews"),
        statHTML(data.count ?? reviews.length, "Total pending"),
      ].join("");
    }
    if (!reviews.length) {
      $("alertReviewQueue").innerHTML = `<div class="item empty-state"><h3>No pending alert reviews</h3><p class="muted">Send an alert to Human Review to create one here.</p></div>`;
      $("alertReviewDetailContainer").style.display = "none";
      return data;
    }
    $("alertReviewQueue").innerHTML = reviews.map(alertReviewCardHTML).join("");
    document.querySelectorAll("[data-alert-review-id]").forEach(button => {
      button.addEventListener("click", () => selectAlertReview(button.dataset.alertReviewId));
    });
    if (currentAlertReviewId && !reviews.some(review => review.id === currentAlertReviewId || review.review_id === currentAlertReviewId)) {
      currentAlertReviewId = null;
      $("alertReviewDetailContainer").style.display = "none";
    }
    return data;
  } catch (err) {
    $("alertReviewQueue").innerHTML = `<div class="item error"><h3>Alert reviews unavailable</h3><p class="muted">${esc(err.message)}</p></div>`;
    $("alertReviewSummary").innerHTML = "";
    $("alertReviewDetailContainer").style.display = "none";
    return null;
  } finally {
    isLoadingAlertReviews = false;
  }
}

async function selectAlertReview(reviewId) {
  currentAlertReviewId = reviewId;
  document.querySelectorAll("[data-alert-review-id]").forEach(item => item.classList.toggle("selected", item.dataset.alertReviewId === reviewId));
  try {
    const data = await api("/human-review/pending");
    const review = (data.reviews || []).find(item => item.id === reviewId || item.review_id === reviewId);
    if (!review) throw new Error("Alert review not found");
    renderAlertReviewDetail(review);
  } catch (err) {
    toast(`ERROR: Failed to load alert review — ${err.message}`);
  }
}

async function submitAlertReviewVerdict(event) {
  event.preventDefault();
  if (isSubmittingAlertVerdict) {
    toast("Submission already in progress");
    return;
  }
  const verdict = ($("alertVerdictInput").value || "").trim();
  const correction = ($("alertCorrectionInput").value || "").trim();
  const confidenceRaw = ($("alertConfidenceInput").value || "").trim();
  const reason = ($("alertReasonInput").value || "").trim();
  const confidence = confidenceRaw ? Number(confidenceRaw) : null;
  const errors = {
    alertVerdictError: "",
    alertCorrectionError: "",
    alertConfidenceError: "",
    alertReasonError: "",
  };
  if (!verdict) errors.alertVerdictError = "Please select a verdict";
  if (verdict === "correct" && !correction) errors.alertCorrectionError = "Correction is required for Correct verdict";
  if (["reject", "needs_more_evidence"].includes(verdict) && !reason) errors.alertReasonError = "Reason is required for this verdict";
  if (confidence !== null && (!Number.isFinite(confidence) || confidence < 0 || confidence > 1)) {
    errors.alertConfidenceError = "Confidence must be a number between 0 and 1";
  }
  Object.entries(errors).forEach(([id, value]) => { $(id).textContent = value; });
  if (Object.values(errors).some(Boolean)) {
    toast("Please fix validation errors before submitting");
    return;
  }
  const button = $("alertSubmitBtn");
  const originalText = button.textContent;
  isSubmittingAlertVerdict = true;
  button.disabled = true;
  button.textContent = "Saving...";
  await visibleFeedbackDelay();
  try {
    const data = await api(`/human-review/${encodeURIComponent(currentAlertReviewId)}/verdict`, {
      method: "POST",
      body: JSON.stringify({
        verdict,
        correction: correction || null,
        confidence: confidence ?? undefined,
        reason: reason || null,
        reviewed_by: "analyst",
      }),
    });
    if (data.status !== "completed") throw new Error("Server did not confirm verdict completion");
    toast("Alert review saved successfully");
    currentAlertReviewId = null;
    $("alertReviewDetailContainer").style.display = "none";
    await loadAlertReviews();
    await loadAlerts({ silent: true });
  } catch (err) {
    toast(`ERROR: Failed to save alert review — ${err.message}`);
    button.textContent = "Failed — Retry";
    return;
  } finally {
    isSubmittingAlertVerdict = false;
    button.disabled = false;
    if (button.textContent !== "Failed — Retry") button.textContent = originalText;
  }
}

function stockManualEvidenceBullets(analysis = {}) {
  const quote = analysis.quote || {};
  const financials = analysis.financials || {};
  const news = analysis.news || [];
  const bullets = [];
  if (quote.price !== undefined && quote.price !== null) {
    bullets.push(`Latest available quote ${fmtMoney(quote.price, quote.currency)}`);
  }
  if (quote.provider_timestamp) {
    bullets.push(`Provider timestamp ${fmtDate(quote.provider_timestamp)}`);
  }
  if (quote.previous_close !== undefined && quote.previous_close !== null) {
    bullets.push(`Previous close ${fmtMoney(quote.previous_close, quote.currency)}`);
  }
  if (financials.latest_quarter?.revenue?.display) {
    bullets.push(`Latest SEC quarter revenue ${financials.latest_quarter.revenue.display}`);
  }
  if (news.length) {
    bullets.push(`Recent Yahoo Finance headlines scanned: ${news.length}`);
  }
  return bullets.slice(0, 4);
}

function manualStockResultHTML(payload) {
  const analysis = payload.analysis || {};
  const company = analysis.company || {};
  const decision = analysis.decision_frame || {};
  const quote = analysis.quote || {};
  const signals = analysis.signals || [];
  const memoryCount = (analysis.memory_context || []).length;
  const bullets = stockManualEvidenceBullets(analysis);
  return `<div class="item">
    <h3>${esc(company.symbol || "")} ${esc(company.name || "")}</h3>
    <div class="meta">
      <span class="tag">${esc(decision.action || "Needs review")}</span>
      <span class="tag">${esc(fmtMoney(quote.price, quote.currency))}</span>
      <span class="tag">${esc(fmtPct(quote.one_year_return))}</span>
      <span class="tag">${esc(quote.market_state || "Latest available")}</span>
    </div>
    <p class="muted">${esc(decision.reason || "")}</p>
    ${kvHTML("Provider", [analysis.provider?.quote, analysis.provider?.news, analysis.provider?.financials].filter(Boolean).join(" · ") || "Yahoo Finance chart + Yahoo Finance RSS + SEC companyfacts")}
    ${kvHTML("Next Step", decision.next_step || "")}
    ${kvHTML("Tracking Metric", decision.tracking_metric || "")}
    ${kvHTML("Fetched at", fmtDate(analysis.generated_at || ""))}
    ${kvHTML("Provider timestamp", quote.provider_timestamp ? fmtDate(quote.provider_timestamp) : "n/a")}
    ${kvHTML("Signals", signals.slice(0, 4).map(s => s.signal).filter(Boolean).join(" · "))}
    ${kvHTML("Memory Matches", memoryCount)}
    <div class="item-sublist">
      <b>Evidence</b>
      ${bullets.length ? `<ul>${bullets.map(line => `<li>${esc(line)}</li>`).join("")}</ul>` : `<p class="muted">No evidence bullets available.</p>`}
    </div>
    <div class="kv"><b>Sources</b><span>${stockSourceLinksHTML(analysis.source_links || {})}</span></div>
  </div>`;
}

async function analyzeStock() {
  const symbol = $("stockTicker").value.trim();
  if (!symbol) {
    toast("Enter a ticker");
    return;
  }
  try {
    const res = await api(`/stock/analyze?symbol=${encodeURIComponent(symbol)}&company=${encodeURIComponent($("stockCompany").value.trim())}`);
    stockIntelData = res;
    $("stockOutput").innerHTML = manualStockResultHTML(res);
    $("saveStockBtn").disabled = true;
    toast("Latest available quote loaded");
  } catch (err) {
    $("stockOutput").innerHTML = `<div class="item error"><h3>Probe Failed</h3><p class="muted">${esc(err.message)}</p></div>`;
    toast(`Latest available quote failed: ${err.message}`);
  }
}

let currentTestSession = null;
let currentReviewId = null;
let isLoadingTestMode = false;
let isImportingFixture = false;
let isSubmittingVerdict = false;

function testHeaders() {
  return {
    "X-Info-Analyzer-Environment": "test",
    "X-Info-Analyzer-Test-Session": currentTestSession || "",
  };
}

function renderSessionError(message) {
  $("reviewContainer").style.display = "block";
  $("pendingReviewsList").innerHTML = `<div class="item error"><h3>Session Error</h3><p class="muted">${esc(message)}</p></div>`;
  $("reviewDetailContainer").style.display = "none";
  $("historyContainer").style.display = "none";
}

function updateTestModeUI(status) {
  const banner = $("testModeBanner");
  const statusEl = $("testModeStatus");
  const dbPathEl = $("testModeDbPath");
  const toggle = $("testModeToggle");
  const container = $("reviewContainer");

  if (!banner || !statusEl || !dbPathEl || !toggle || !container) return;

  if (status.error) {
    currentTestSession = status.session_id || currentTestSession || null;
    statusEl.textContent = "Error";
    banner.className = "banner banner-error";
    dbPathEl.textContent = `Error: ${status.error}`;
    toggle.textContent = "Enable Test Mode";
    renderSessionError(status.error);
    return;
  }

  if (status.active) {
    currentTestSession = status.session_id;
    window.__infoAnalyzerTestSession = currentTestSession;
    statusEl.textContent = "Enabled";
    banner.className = "banner banner-success";
    const dbName = (status.test_db_path || "").split("/").pop();
    dbPathEl.textContent = `Session: ${status.session_id} | DB: .../${dbName}`;
    toggle.textContent = "Disable Test Mode";
    container.style.display = "block";
    loadPendingReviews();
    return;
  }

  currentTestSession = null;
  statusEl.textContent = "Disabled";
  banner.className = "banner banner-info";
  dbPathEl.textContent = status.message || "Test Mode is off";
  toggle.textContent = "Enable Test Mode";
  container.style.display = status.keep_container ? "block" : "none";
  if (status.keep_container) renderSessionError(status.message || "Test Mode is disabled. Enable a session before taking review actions.");
}

async function loadTestModeStatus() {
  if (!$("testModeBanner")) return;
  isLoadingTestMode = true;
  $("testModeBanner").className = "banner banner-loading";
  $("testModeStatus").textContent = "Loading...";
  try {
    const data = await api("/test-mode/status");
    updateTestModeUI(data);
  } catch (err) {
    updateTestModeUI({ active: false, error: err.message });
  } finally {
    isLoadingTestMode = false;
    if ($("testModeToggle")) $("testModeToggle").disabled = false;
  }
}

async function toggleTestMode() {
  if (isLoadingTestMode) return;
  const toggle = $("testModeToggle");
  toggle.disabled = true;
  if (currentTestSession) {
    try {
      await api("/test-mode/disable", {
        method: "POST",
        headers: testHeaders(),
        body: "{}",
      });
      const disabledSession = currentTestSession;
      currentTestSession = null;
      window.__infoAnalyzerTestSession = disabledSession;
      updateTestModeUI({
        active: false,
        keep_container: true,
        message: "Test Mode session disabled. Further review actions require a new session.",
      });
      toast("Test Mode disabled");
    } catch (err) {
      updateTestModeUI({ active: false, error: err.message, session_id: currentTestSession });
      toast(`ERROR: Failed to disable Test Mode — ${err.message}`);
    } finally {
      toggle.disabled = false;
    }
    return;
  }

  try {
    $("testModeBanner").className = "banner banner-loading";
    $("testModeStatus").textContent = "Loading...";
    await visibleFeedbackDelay();
    const data = await api("/test-mode/enable", {
      method: "POST",
      body: "{}",
    });
    updateTestModeUI({ active: true, ...data });
    toast("Test Mode enabled");
  } catch (err) {
    updateTestModeUI({ active: false, error: err.message });
    toast(`ERROR: Failed to enable Test Mode — ${err.message}`);
  } finally {
    toggle.disabled = false;
  }
}

async function loadPendingReviews() {
  if (!currentTestSession) {
    renderSessionError("Invalid or disabled Test Mode session");
    return;
  }
  $("pendingReviewsList").innerHTML = `<div class="item"><p class="muted">Loading reviews...</p></div>`;
  try {
    const data = await api("/workbench/reviews", { headers: testHeaders() });
    const pending = (data.reviews || []).filter(review => review.status === "pending");
    if (!pending.length) {
      $("pendingReviewsList").innerHTML = `<div class="item empty-state"><h3>No Pending Reviews</h3><p class="muted">Import a fixture to create a review.</p></div>`;
    } else {
      $("pendingReviewsList").innerHTML = pending.map(review => `
        <button class="item review-item" data-review-id="${esc(review.review_id)}">
          <h3>${esc(review.review_id)}</h3>
          <div class="meta"><span class="tag">pending</span><span class="tag">${esc(review.subject_type || "")}</span></div>
          <p class="muted">${esc(review.original_value || "(no machine proposal)")}</p>
        </button>
      `).join("");
      document.querySelectorAll("[data-review-id]").forEach(button => {
        button.addEventListener("click", () => selectReview(button.dataset.reviewId));
      });
    }
    await loadReviewHistory();
  } catch (err) {
    renderSessionError(err.message);
    toast(`ERROR: Failed to load reviews — ${err.message}`);
  }
}

async function importFixture() {
  if (!currentTestSession) {
    renderSessionError("Invalid or disabled Test Mode session");
    toast("ERROR: Test Mode not enabled");
    return;
  }
  if (isImportingFixture) {
    toast("Import already in progress");
    return;
  }
  const button = $("importFixtureBtn");
  const originalText = button.textContent;
  isImportingFixture = true;
  button.disabled = true;
  button.textContent = "Importing...";
  await visibleFeedbackDelay();
  try {
    const unique = Date.now();
    await api("/workbench/fixtures/import", {
      method: "POST",
      headers: testHeaders(),
      body: JSON.stringify({
        fixture_data: { entity: `Human Review Fixture ${unique}`, claim: `Machine proposal ${unique}` },
        url: `https://example.invalid/human-review/${unique}`,
        title: `Human Review Fixture ${unique}`,
        proposed_value: `normalized test value ${unique}`,
        confidence: 0.75,
      }),
    });
    toast("Fixture imported — new review added to queue");
    await loadPendingReviews();
  } catch (err) {
    toast(`ERROR: Import failed — ${err.message}`);
  } finally {
    isImportingFixture = false;
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function selectReview(reviewId) {
  currentReviewId = reviewId;
  document.querySelectorAll("[data-review-id]").forEach(item => item.classList.toggle("selected", item.dataset.reviewId === reviewId));
  try {
    const data = await api("/workbench/reviews", { headers: testHeaders() });
    const review = (data.reviews || []).find(item => item.review_id === reviewId);
    if (!review) throw new Error("Review not found");
    displayReviewDetail(review);
  } catch (err) {
    toast(`ERROR: Failed to load review — ${err.message}`);
  }
}

function displayReviewDetail(review) {
  $("reviewDetailContainer").style.display = "block";
  $("reviewDetail").innerHTML = `
    <div class="review-evidence section">
      <h3>Original Evidence</h3>
      ${kvHTML("Subject", review.subject_id || "")}
      ${kvHTML("Type", review.subject_type || "")}
      ${kvHTML("Evidence ID", review.evidence_id || "")}
    </div>
    <div class="review-proposal section">
      <h3>System Proposal</h3>
      <p class="muted">${esc(review.original_value || "(system proposal unavailable)")}</p>
      ${kvHTML("System Confidence", Number(review.system_confidence || 0).toFixed(2))}
    </div>
    <div class="review-judgment section">
      <h3>Your Judgment</h3>
      <form id="verdictForm" novalidate>
        <div class="form-group">
          <label>Verdict</label>
          <div id="verdictError" class="field-error"></div>
          <div class="button-group">
            <button type="button" class="verdict-btn" data-verdict="confirm">Confirm</button>
            <button type="button" class="verdict-btn" data-verdict="correct">Correct</button>
            <button type="button" class="verdict-btn" data-verdict="reject">Reject</button>
            <button type="button" class="verdict-btn" data-verdict="needs_more_evidence">Needs More Evidence</button>
          </div>
          <input type="hidden" id="verdictInput" />
        </div>
        <div class="form-group">
          <label>Correction <span id="correctionRequired" class="required" style="display:none">*</span></label>
          <div id="correctionError" class="field-error"></div>
          <input id="correctionInput" placeholder="Enter corrected interpretation" />
        </div>
        <div class="form-group">
          <label>Human Confidence</label>
          <div id="confidenceError" class="field-error"></div>
          <input id="confidenceInput" type="number" min="0" max="1" step="0.01" placeholder="0.75" />
        </div>
        <div class="form-group">
          <label>Reason <span id="reasonRequired" class="required" style="display:none">*</span></label>
          <div id="reasonError" class="field-error"></div>
          <textarea id="reasonInput" placeholder="Required for Reject and Needs More Evidence"></textarea>
        </div>
        <div class="buttons"><button id="submitBtn" class="primary" type="submit">Save Verdict</button></div>
      </form>
    </div>
  `;
  document.querySelectorAll(".verdict-btn").forEach(button => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".verdict-btn").forEach(item => item.classList.remove("selected"));
      button.classList.add("selected");
      $("verdictInput").value = button.dataset.verdict;
      $("correctionRequired").style.display = button.dataset.verdict === "correct" ? "inline" : "none";
      $("reasonRequired").style.display = ["reject", "needs_more_evidence"].includes(button.dataset.verdict) ? "inline" : "none";
    });
  });
  $("verdictForm").addEventListener("submit", submitVerdict);
}

async function submitVerdict(event) {
  event.preventDefault();
  if (isSubmittingVerdict) {
    toast("Submission already in progress");
    return;
  }
  const verdict = ($("verdictInput").value || "").trim();
  const correction = ($("correctionInput").value || "").trim();
  const confidenceRaw = ($("confidenceInput").value || "").trim();
  const reason = ($("reasonInput").value || "").trim();
  const confidence = confidenceRaw ? Number(confidenceRaw) : null;
  const errors = {
    verdictError: "",
    correctionError: "",
    confidenceError: "",
    reasonError: "",
  };
  if (!verdict) errors.verdictError = "Please select a verdict";
  if (verdict === "correct" && !correction) errors.correctionError = "Correction is required for Correct verdict";
  if (["reject", "needs_more_evidence"].includes(verdict) && !reason) errors.reasonError = "Reason is required for this verdict";
  if (confidence !== null && (!Number.isFinite(confidence) || confidence < 0 || confidence > 1)) {
    errors.confidenceError = "Confidence must be a number between 0 and 1";
  }
  Object.entries(errors).forEach(([id, value]) => { $(id).textContent = value; });
  if (Object.values(errors).some(Boolean)) {
    toast("Please fix validation errors before submitting");
    return;
  }
  const button = $("submitBtn");
  const originalText = button.textContent;
  isSubmittingVerdict = true;
  button.disabled = true;
  button.textContent = "Saving...";
  await visibleFeedbackDelay();
  try {
    const data = await api(`/workbench/reviews/${encodeURIComponent(currentReviewId)}/verdict`, {
      method: "POST",
      headers: testHeaders(),
      body: JSON.stringify({
        verdict,
        corrected_value: correction || null,
        human_confidence: confidence ?? undefined,
        reason: reason || null,
      }),
    });
    if (data.status !== "completed") throw new Error("Server did not confirm verdict completion");
    toast("Verdict saved successfully");
    currentReviewId = null;
    $("reviewDetailContainer").style.display = "none";
    await loadPendingReviews();
  } catch (err) {
    toast(`ERROR: Failed to save verdict — ${err.message}`);
    button.textContent = "Failed — Retry";
    return;
  } finally {
    isSubmittingVerdict = false;
    button.disabled = false;
    if (button.textContent !== "Failed — Retry") button.textContent = originalText;
  }
}

async function loadReviewHistory() {
  if (!currentTestSession) return;
  $("historyContainer").style.display = "block";
  $("historyList").innerHTML = `<div class="item"><p class="muted">Loading history...</p></div>`;
  try {
    const data = await api("/workbench/reviews", { headers: testHeaders() });
    const completed = (data.reviews || []).filter(review => review.status === "completed");
    $("historyList").innerHTML = completed.length
      ? completed.map(review => `
        <div class="item">
          <h3>${esc(review.review_id)}</h3>
          <div class="meta"><span class="tag">completed</span><span class="tag">${esc(review.human_verdict || "")}</span></div>
          ${kvHTML("Confidence", Number(review.human_confidence || 0).toFixed(2))}
          ${kvHTML("Correction", review.corrected_value || "")}
          ${kvHTML("Reason", review.reason || "")}
        </div>
      `).join("")
      : `<div class="item empty-state"><h3>No Completed Reviews</h3><p class="muted">Your saved reviews will appear here.</p></div>`;
  } catch (err) {
    $("historyList").innerHTML = `<div class="item error"><h3>ERROR</h3><p class="muted">Failed to load history: ${esc(err.message)}</p></div>`;
  }
}

function renderBuildInfoHeader(data) {
  if ($("appVersion")) $("appVersion").textContent = data.application_version || "";
  document.title = `Info Analyzer OS ${data.application_version || ""}`.trim();
}

function renderBootstrapState() {
  if (!bootstrapData) return;
  buildInfo = bootstrapData;
  renderBuildInfoHeader(bootstrapData);
  if (bootstrapInitialView === "overview" && bootstrapData.overview && $("overviewStats")) {
    renderOverview(bootstrapData.overview);
  }
}

function bindViewButtons() {
  document.querySelectorAll("[data-view]").forEach(btn => {
    btn.addEventListener("click", () => setActiveView(btn.dataset.view));
  });
}

function bindRefreshButtons() {
  $("refreshRuntimeStatus")?.addEventListener("click", loadRuntimeStatus);
  $("refreshOverview")?.addEventListener("click", loadOverview);
  $("refreshInbox")?.addEventListener("click", loadRecentCaptures);
  $("refreshContextLibrary")?.addEventListener("click", loadContextLibrary);
  $("processInvestingQueue")?.addEventListener("click", processInvestingQueue);
  $("captureSignalBtn")?.addEventListener("click", captureSignal);
  $("createSourceBtn")?.addEventListener("click", createSourceFromUI);
  $("runLatestSourceBtn")?.addEventListener("click", () => runSourcePull(latestCreatedSourceId));
  $("refreshSources")?.addEventListener("click", loadSources);
  $("refreshEvidence")?.addEventListener("click", loadEvidence);
  $("refreshSystemHealth")?.addEventListener("click", loadSystemHealth);
  $("refreshAlerts")?.addEventListener("click", refreshAlertCenter);
  $("runAlertCheck")?.addEventListener("click", runAlertCheck);
  $("createTestAlert")?.addEventListener("click", createTestAlert);
  $("refreshLocalSource")?.addEventListener("click", loadLocalSourceStatus);
  $("refreshAlertReviews")?.addEventListener("click", loadAlertReviews);
  $("refreshStockIntel")?.addEventListener("click", () => loadStockIntel());
  $("refreshStockSnapshotHistory")?.addEventListener("click", loadStockSnapshotHistory);
  $("refreshStockHistory")?.addEventListener("click", loadStockSnapshotHistory);
  $("refreshStockReviews")?.addEventListener("click", loadStockHumanReviews);
  $("addStockTicker")?.addEventListener("click", () => {
    const next = String($("stockWatchlistInput")?.value || "").trim().toUpperCase();
    if (!next) {
      toast("Enter a ticker");
      return;
    }
    saveStockWatchlist([...stockWatchlist, next]);
    if ($("stockWatchlistInput")) $("stockWatchlistInput").value = "";
    loadStockIntel().catch(() => {});
  });
  $("stockWatchlistInput")?.addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      $("addStockTicker")?.click();
    }
  });
  $("clearStockWatchlist")?.addEventListener("click", () => {
    saveStockWatchlist([]);
    loadStockIntel().catch(() => {});
  });
  $("resetStockWatchlist")?.addEventListener("click", () => {
    saveStockWatchlist(DEFAULT_STOCK_WATCHLIST);
    loadStockIntel().catch(() => {});
  });
  $("stockSnapshotMode")?.addEventListener("change", () => setCurrentStockMode(currentStockMode()));
  $("analyzeStockBtn")?.addEventListener("click", analyzeStock);
  $("testModeToggle")?.addEventListener("click", toggleTestMode);
  $("importFixtureBtn")?.addEventListener("click", importFixture);
  $("refreshJobsRuns")?.addEventListener("click", loadJobsRuns);
  $("refreshBuildInfo")?.addEventListener("click", loadBuildInformation);
  $("refreshLegacyArchive")?.addEventListener("click", loadLegacyArchive);
}

document.addEventListener("click", event => {
  const button = event.target.closest("[data-select-evidence]");
  if (button) {
    selectEvidence(Number(button.dataset.selectEvidence));
  }
  const alertButton = event.target.closest("[data-alert-action]");
  if (alertButton) {
    const alertId = alertButton.dataset.alertId || "";
    const action = alertButton.dataset.alertAction || "";
    if (!alertId || !action) return;
    if (action === "acknowledge" || action === "dismiss" || action === "send-review" || action === "convert-action") {
      const promise = action === "send-review"
        ? performAlertAction(alertId, action)
        : performAlertAction(alertId, action);
      promise.then(result => {
        if (action === "send-review" && result?.review_id) {
          toast("Alert sent to Human Review");
        } else if (action === "convert-action" && result?.action?.id) {
          toast("Alert converted to canonical action");
        } else {
          toast(`Alert ${action}`);
        }
      }).catch(err => toast(`Alert action failed: ${err.message}`));
      return;
    }
  }
  const snoozeButton = event.target.closest("[data-alert-snooze]");
  if (snoozeButton) {
    const alertId = snoozeButton.dataset.alertId || "";
    const minutes = Number(snoozeButton.dataset.alertSnooze || 0);
    if (!alertId || !minutes) return;
    performAlertAction(alertId, "snooze", { minutes })
      .then(() => toast(`Alert snoozed for ${minutes >= 1440 ? "1 day" : minutes >= 240 ? "4 hours" : minutes >= 60 ? "1 hour" : "15 minutes"}`))
      .catch(err => toast(`Alert snooze failed: ${err.message}`));
    return;
  }
  const processButton = event.target.closest("[data-process-observation]");
  if (processButton) {
    processObservation(processButton.dataset.processObservation);
  }
  const runSourceButton = event.target.closest("[data-run-source]");
  if (runSourceButton) {
    latestCreatedSourceId = runSourceButton.dataset.runSource || "";
    runSourcePull(latestCreatedSourceId);
  }
  const evidenceButton = event.target.closest("[data-open-source-evidence]");
  if (evidenceButton) {
    setActiveView("evidence");
  }
});

async function loadOverview() {
  try {
    overviewData = buildInfo?.overview || await api("/overview");
    renderOverview(overviewData);
  } catch (err) {
    renderRuntimeDisconnected(err);
    $("overviewStats").innerHTML = "";
    $("overviewIntervention").innerHTML = `<div class="item error"><h3>Overview unavailable</h3><p class="muted">${esc(err.message)}</p></div>`;
    $("overviewUnavailable").innerHTML = "";
    $("overviewLatestFailure").innerHTML = "";
  }
}

async function loadInitialBuildInfo() {
  const data = await refreshBuildInfo();
  renderBuildInfoHeader(buildInfo);
  return data;
}

async function boot() {
  renderBootstrapState();
  bindViewButtons();
  bindRefreshButtons();
  stockWatchlist = loadStockWatchlist();
  if ($("stockSnapshotMode")) $("stockSnapshotMode").value = loadStoredStockMode();
  await loadRuntimeStatus();
  try {
    await loadInitialBuildInfo();
  } catch (err) {
    renderRuntimeDisconnected(err);
  }
  const initialView = readViewFromUrl() || readSavedView();
  setActiveView(initialView);
}

window.addEventListener("load", boot);
