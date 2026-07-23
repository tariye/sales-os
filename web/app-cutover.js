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
  "human-review",
  "sources",
  "evidence",
  "system-health",
  "stock-intel",
  "jobs-runs",
  "build-information",
  "legacy-archive",
  "help",
]);

let buildInfo = null;
let overviewData = null;
let sourcesData = null;
let evidenceData = null;
let healthData = null;
let jobsRunsData = null;
let legacyData = null;
let stockIntelData = null;
const bootstrapData = window.__CUTOVER_BOOTSTRAP__ || null;
const bootstrapInitialView = normalizeView(new URLSearchParams(window.location.search).get(VIEW_QUERY_KEY) || new URLSearchParams(window.location.search).get("tab") || "");

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
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZoneName: "short",
  }).format(d);
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

function kvHTML(label, value) {
  return value || value === 0 ? `<div class="kv"><b>${esc(label)}</b><span>${esc(value)}</span></div>` : "";
}

function normalizeView(view) {
  return VIEWS.has(view) ? view : DEFAULT_VIEW;
}

function readViewFromUrl() {
  const params = new URLSearchParams(window.location.search);
  return normalizeView(params.get(VIEW_QUERY_KEY) || params.get("tab") || "");
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
  persistView(next);
  document.querySelectorAll(".tab").forEach(btn => btn.classList.toggle("active", btn.dataset.view === next));
  document.querySelectorAll(".panel").forEach(panel => panel.classList.toggle("active", panel.id === next));
  if (next === "overview") loadOverview();
  if (next === "human-review") loadTestModeStatus();
  if (next === "sources") loadSources();
  if (next === "evidence") loadEvidence();
  if (next === "system-health") loadSystemHealth();
  if (next === "stock-intel") loadStockIntel();
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
  $("overviewStats").innerHTML = [
    statHTML(data.runtime_health?.quick_check || "n/a", "Runtime Health"),
    statHTML(data.scheduler?.owner_id || "unassigned", "Scheduler Leader"),
    statHTML(data.worker?.heartbeat_at ? fmtDate(data.worker.heartbeat_at) : "n/a", "Worker Heartbeat"),
    statHTML(data.source_counts?.active ?? 0, "Active Sources"),
    statHTML(data.source_counts?.healthy ?? 0, "Healthy"),
    statHTML(data.source_counts?.retrying ?? 0, "Retrying"),
    statHTML(data.source_counts?.stale ?? 0, "Stale"),
    statHTML(data.source_counts?.failed ?? 0, "Failed"),
    statHTML(data.source_counts?.dead_letter ?? 0, "Dead Letter"),
    statHTML(data.evidence_captured_today ?? 0, "Evidence Captured Today"),
    statHTML(`${data.jobs_pending ?? 0} / ${data.jobs_running ?? 0}`, "Jobs Pending / Running"),
    statHTML(data.latest_evidence_at ? fmtDate(data.latest_evidence_at) : "n/a", "Latest Evidence"),
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
    <details class="item" style="margin-top:12px">
      <summary>Diagnostics</summary>
      <div class="kv-grid" style="margin-top:10px">
        ${kvHTML("Source ID", source.id || "")}
        ${kvHTML("Job ID", source.last_job_id || "")}
        ${kvHTML("Run ID", source.last_run_id || "")}
        ${kvHTML("Snapshot ID", source.last_snapshot_id || "")}
        ${kvHTML("Claim ID", source.current_claim_id || source.latest_job?.claim_id || "")}
        ${kvHTML("Health Event IDs", (source.recent_health_events || []).map(event => event.id).join(" | "))}
      </div>
      <div class="list" style="margin-top:12px">${history || `<div class="item"><h3>No health history</h3><p class="muted">No health events recorded yet.</p></div>`}</div>
    </details>
  </div>`;
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
      <pre style="white-space:pre-wrap;word-break:break-word;margin:12px 0 0;background:#fffdf8;border:1px solid rgba(24,79,67,.14);border-radius:14px;padding:12px">${esc(snapshot.raw_payload || "")}</pre>
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

function stockResultHTML(payload) {
  const analysis = payload.analysis || {};
  const company = analysis.company || {};
  const decision = analysis.decision_frame || {};
  const signals = analysis.signals || [];
  return `
    <div class="item">
      <h3>${esc(company.symbol || "")} ${esc(company.name || "")}</h3>
      <div class="meta"><span class="tag">pilot</span><span class="tag">${esc(decision.action || "watch")}</span></div>
      ${kvHTML("Reason", decision.reason || "")}
      ${kvHTML("Next Step", decision.next_step || "")}
      ${kvHTML("Tracking Metric", decision.tracking_metric || "")}
      <div class="kv"><b>Signals</b><span>${esc(signals.slice(0, 4).map(s => s.signal).filter(Boolean).join(" | "))}</span></div>
    </div>
  `;
}

async function loadStockIntel() {
  if (!$("stockOutput").innerHTML.trim()) {
    $("stockOutput").innerHTML = `<div class="item"><h3>Ready</h3><p class="muted">Enter a ticker to run a pilot analysis. Save to memory is disabled in this cutover shell.</p></div>`;
  }
}

async function analyzeStock() {
  const symbol = $("stockTicker").value.trim();
  if (!symbol) {
    toast("Enter a ticker");
    return;
  }
  const res = await api(`/stock/analyze?symbol=${encodeURIComponent(symbol)}&company=${encodeURIComponent($("stockCompany").value.trim())}`);
  stockIntelData = res;
  $("stockOutput").innerHTML = stockResultHTML(res);
  $("saveStockBtn").disabled = true;
  toast("Stock analysis loaded");
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
  document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => setActiveView(btn.dataset.view));
  });
}

function bindRefreshButtons() {
  $("refreshOverview")?.addEventListener("click", loadOverview);
  $("refreshSources")?.addEventListener("click", loadSources);
  $("refreshEvidence")?.addEventListener("click", loadEvidence);
  $("refreshSystemHealth")?.addEventListener("click", loadSystemHealth);
  $("refreshStockIntel")?.addEventListener("click", loadStockIntel);
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
});

async function loadOverview() {
  overviewData = buildInfo?.overview || await api("/overview");
  renderOverview(overviewData);
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
  await loadInitialBuildInfo();
  const initialView = readViewFromUrl() || readSavedView();
  setActiveView(initialView);
}

window.addEventListener("load", boot);
