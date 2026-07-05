const API = "/api";
const $ = id => document.getElementById(id);
const esc = v => String(v ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;");
const tagsFrom = s => String(s || "").split(/[#,]/).map(x => x.trim().toLowerCase()).filter(Boolean).filter((x, i, a) => a.indexOf(x) === i);
const nf = new Intl.NumberFormat("en-US");
const moneyf = new Intl.NumberFormat("en-US", { style:"currency", currency:"USD", maximumFractionDigits:0 });
let lastDraft = null;

async function api(path, opts={}){
  const res = await fetch(API + path, { ...opts, headers:{"Content-Type":"application/json", ...(opts.headers||{})} });
  const txt = await res.text();
  const data = txt ? JSON.parse(txt) : {};
  if(!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function toast(msg){
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  setTimeout(()=>t.classList.add("hidden"), 2500);
}

function fmtNumber(v){
  const n = Number(v || 0);
  return Number.isFinite(n) ? nf.format(n) : "0";
}

function fmtPct(v){
  const n = Number(v || 0);
  return Number.isFinite(n) ? `${n.toFixed(1)}%` : "0.0%";
}

function fmtMoney(v){
  const n = Number(v || 0);
  return Number.isFinite(n) ? moneyf.format(n) : "$0";
}

function normText(v){
  return String(v || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function looksGenericAction(value){
  const t = normText(value);
  return !t || [
    "execute the next concrete step and log the result.",
    "define the trigger condition and review date; resurface when the condition appears.",
    "add this to the pattern library and watch for repeats across domains.",
    "define the failure mode, mitigation step, and metric to watch.",
    "run the smallest validation test and track the outcome.",
    "compare against the old thesis and update confidence with evidence.",
    "attach or create a proof artifact and connect it to the relevant entry.",
    "link this as reference context and resurface only when a future input needs it.",
    "archive as raw context unless a future trigger makes it actionable."
  ].includes(t) || /^(review the command surface|execute, then log result back into the db|click track signal)/.test(t);
}

function looksGenericMetric(value){
  const t = normText(value);
  return !t || [
    "entries saved, relevant pulls, action cards executed, false pulls reduced",
    "define metric or observable",
    "observable result",
    "accepted, ignored, or rejected when resurfaced in relevant context",
    "number of repeats and domains where it appears",
    "confidence before/after and evidence that changed it",
    "artifact created and result produced",
    "depends on document/headline content"
  ].includes(t);
}

function looksGenericWhy(value){
  const t = normText(value);
  return !t || [
    "this memory matched the query and can return a decision or action.",
    "this action came from a translated signal.",
    "signal returned an action."
  ].includes(t);
}

function looksGenericFirstStep(value){
  const t = normText(value);
  return !t || [
    "open the entry, execute the returned action, and log the result.",
    "save, retrieve related memories, execute/track action, then log result.",
    "review the command surface, execute the action, then log the result.",
    "execute, then log result back into the db.",
    "click track signal or archive the item.",
    "set next filing or review date."
  ].includes(t);
}

function meaningfulLesson(entry){
  const lesson = String(entry.lesson || "").trim();
  if(!lesson || lesson.length < 18) return "";
  const lessonNorm = normText(lesson);
  if(lessonNorm === normText(entry.signal) || lessonNorm === normText(entry.interpretation) || lessonNorm === normText(entry.raw_input)) return "";
  return lesson;
}

function meaningfulWhy(value){
  const text = String(value || "").trim();
  return looksGenericWhy(text) ? "" : text;
}

function meaningfulAction(entry){
  const value = String(entry.returned_action || "").trim();
  if(entry.status === "pending_claude" || entry.status === "raw" || entry.status === "needs_enrichment") return "";
  return looksGenericAction(value) ? "" : value;
}

function meaningfulFirstStep(entry){
  const value = String(entry.first_step || "").trim();
  if(entry.status === "pending_claude" || entry.status === "raw" || entry.status === "needs_enrichment") return "";
  if(!value || looksGenericFirstStep(value)) return "";
  const action = meaningfulAction(entry);
  if(action && normText(value) === normText(action)) return "";
  return value;
}

function meaningfulMetric(entry){
  const value = String(entry.tracking_metric || "").trim();
  if(entry.status === "pending_claude" || entry.status === "raw" || entry.status === "needs_enrichment") return "";
  return looksGenericMetric(value) ? "" : value;
}

function meaningfulActionText(value){
  const text = String(value || "").trim();
  return looksGenericAction(text) ? "" : text;
}

function meaningfulMetricText(value){
  const text = String(value || "").trim();
  return looksGenericMetric(text) ? "" : text;
}

function meaningfulStepText(value){
  const text = String(value || "").trim();
  return looksGenericFirstStep(text) ? "" : text;
}

function kvHTML(label, value){
  return value ? `<div class="kv"><b>${esc(label)}</b><span>${esc(value)}</span></div>` : "";
}

function statHTML(label, value, extra=""){
  return `<div class="stat ${extra}"><strong>${esc(value)}</strong><span class="muted">${esc(label)}</span></div>`;
}

function compactItem(title, body, meta=[]){
  return `<div class="item"><h3>${esc(title)}</h3>${meta.length ? `<div class="meta">${meta.map(m=>`<span class="tag">${esc(m)}</span>`).join("")}</div>` : ""}<p class="muted">${esc(body)}</p></div>`;
}

function enrichBadge(e){
  const s = e.status || "";
  const hasAI = !!(e.interpretation && e.interpretation.trim());
  const isChild = !!(e.parent_entry_id && e.parent_entry_id.trim());
  if(s === "pending_claude" || s === "raw") return `<span class="enrich-badge eb-queued">Queued</span>`;
  if(s === "needs_enrichment") return `<span class="enrich-badge eb-needs">Needs Enrichment</span>`;
  if(isChild) return `<span class="enrich-badge eb-child">Extracted</span>`;
  if(hasAI) return `<span class="enrich-badge eb-enriched">AI Enriched</span>`;
  return `<span class="enrich-badge eb-raw">Codified</span>`;
}

function entryHTML(e){
  const inQueue = e.status === "pending_claude" || e.status === "raw" || e.status === "needs_enrichment";
  const interp = (e.interpretation || "").trim();
  const lesson = meaningfulLesson(e);
  const action = meaningfulAction(e);
  const firstStep = meaningfulFirstStep(e);
  const metric = meaningfulMetric(e);
  const queueLabel = e.status === "needs_enrichment" ? "Needs Enrichment" : (inQueue ? "In Queue" : "Queue for Claude");
  return `<div class="item${inQueue ? " item-queued" : ""}">
    <div class="entry-top">${enrichBadge(e)}<h3>${esc(e.title || e.id)}</h3></div>
    <div class="meta"><span class="tag">${esc(e.domain)}</span><span class="tag">${esc(e.signal_role)}</span>${(e.tags || []).slice(0,4).map(t=>`<span class="tag">${esc(t)}</span>`).join("")}</div>
    ${interp ? `<p class="entry-interp">${esc(interp.slice(0, 240))}</p>` : `<p class="muted">${esc((e.signal || e.raw_input || "").slice(0, 240))}</p>`}
    ${kvHTML("Lesson", lesson ? lesson.slice(0, 180) : "")}
    ${kvHTML("Action", action)}
    ${kvHTML("First Step", firstStep)}
    ${kvHTML("Metric", metric)}
    <div class="buttons compact"><button class="ghost small ${inQueue ? "queue-active" : ""}" onclick="queueForClaude('${esc(e.id)}', this)">${queueLabel}</button></div>
  </div>`;
}

function queueEntryHTML(e){
  const age = e.created_at ? e.created_at.slice(0,10) : "";
  const badge = e.status === "needs_enrichment" ? "Needs Enrichment" : "Queued";
  return `<div class="item item-queued">
    <div class="entry-top"><span class="enrich-badge ${e.status === "needs_enrichment" ? "eb-needs" : "eb-queued"}">${esc(badge)}</span><h3>${esc(e.title || e.id)}</h3></div>
    <div class="meta"><span class="tag">${esc(e.domain || "Other")}</span>${e.entity ? `<span class="tag">${esc(e.entity)}</span>` : ""}${age ? `<span class="tag">${esc(age)}</span>` : ""}</div>
    <p class="muted">${esc((e.raw_input || "").slice(0, 260))}</p>
    <div class="buttons compact"><button class="ghost small queue-active" onclick="queueForClaude('${esc(e.id)}', this)">${esc(badge)}</button></div>
  </div>`;
}

function actionHTML(a){
  const card = a.execution_card || {};
  const why = meaningfulWhy(card.why_it_matters || a.why || "");
  const track = meaningfulMetricText(card.track || a.track_metric || "");
  const steps = (card.exact_actions || []).map(s => `<li>${esc(s)}</li>`).join("");
  const doneBtn = a.status !== "done" ? `<button class="primary small" onclick="markDone('${esc(a.id)}')">Mark Done</button>` : "";
  const patternBtn = `<button class="ghost small" onclick="extractPatternFromAction('${esc(a.id)}','${esc(a.entry_id)}')">Extract Pattern</button>`;
  const abortBtn = a.status !== "cancelled" ? `<button class="ghost small danger-btn" onclick="abortAction('${esc(a.id)}')">Abort</button>` : "";
  return `<div class="item action-card">
    <h3>${esc(card.action_name || a.action_title)}</h3>
    <div class="meta"><span class="tag">${esc(a.status)}</span><span class="tag">${esc(a.priority)}</span>${a.due_date ? `<span class="tag">due ${esc(a.due_date)}</span>` : ""}</div>
    <div class="kv"><b>Source</b><span>${esc(card.source || a.source_title || a.entry_id)}</span></div>
    ${kvHTML("Why it matters", why)}
    ${steps ? `<div class="kv"><b>Exact actions</b><span><ol class="steps">${steps}</ol></span></div>` : ""}
    ${kvHTML("Track", track)}
    <div class="buttons">${doneBtn}${patternBtn}${abortBtn}</div>
  </div>`;
}

function pamaCardHTML(c){
  const why = meaningfulWhy(c.why_it_matters || "");
  const action = meaningfulActionText(c.recommended_action || "");
  const step = meaningfulStepText(c.first_step || "");
  const track = meaningfulMetricText(c.tracking_metric || "");
  return `<div class="item action-card">
    <h3>${esc(c.title || c.signal || c.entry_id)}</h3>
    <div class="meta"><span class="tag">${esc(c.domain || "")}</span><span class="tag">${esc(c.tier || "")}</span><span class="tag">score ${esc(c.score)}</span></div>
    ${kvHTML("Why", why)}
    ${kvHTML("Action", action)}
    ${kvHTML("First Step", step)}
    ${kvHTML("Track", track)}
    <div class="buttons">
      <button class="ghost small danger-btn" onclick="dismissSignal('${esc(c.entry_id)}')">Dismiss</button>
      <button class="primary small" onclick="actOnSignal('${esc(c.entry_id)}','${esc(c.recommended_action || c.title || "")}')">Done — Log Result</button>
      <button class="ghost small" onclick="recontextualizeSignal('${esc(c.entry_id)}')">Re-translate</button>
    </div>
  </div>`;
}

function changelogEntryHTML(v, currentVersion){
  const isCurrent = v.version === currentVersion;
  return `<div class="cl-entry${isCurrent ? " cl-current" : ""}">
    <div class="cl-head">
      <span class="cl-badge${isCurrent ? " cl-badge-current" : ""}">${esc(v.version)}</span>
      <span class="cl-name">${esc(v.name)}</span>
      ${isCurrent ? `<span class="pill good cl-pill">current</span>` : ""}
    </div>
    <ul class="cl-features">${(v.features || []).map(f=>`<li>${esc(f)}</li>`).join("")}</ul>
  </div>`;
}

function collectBase(){
  return {
    raw_input: $("rawInput").value.trim(),
    domain: $("domainInput").value,
    source_type: $("sourceTypeInput").value || "",
    entity: $("entityInput").value.trim(),
    tags: tagsFrom($("tagsInput").value)
  };
}

function collectDraft(){
  const base = collectBase();
  return {
    ...base,
    title: $("titleInput").value.trim(),
    signal_role: $("signalRoleInput").value,
    confidence: $("confidenceInput").value,
    actionability: $("actionabilityInput").value,
    card_type: $("cardTypeInput").value,
    pull_trigger_type: $("pullTriggerTypeInput").value,
    relationship_type: $("relationshipTypeInput").value,
    signal: $("signalInput").value.trim(),
    interpretation: $("interpretationInput").value.trim(),
    trackable_as: $("trackableAsInput").value.trim(),
    tracking_metric: $("trackingMetricInput").value.trim(),
    baseline: $("baselineInput").value.trim(),
    target_threshold: $("targetInput").value.trim(),
    pull_trigger: $("pullTriggerInput").value.trim(),
    trigger_condition: $("triggerInput").value.trim(),
    result_to_track: $("resultToTrackInput").value.trim(),
    first_step: $("firstStepInput").value.trim(),
    impact_metric: $("impactMetricInput").value.trim(),
    feedback_to_capture: $("feedbackInput").value.trim(),
    related_memory_query: $("relatedQueryInput").value.trim(),
    qa_scores: lastDraft?.qa_scores || {},
    pattern: $("patternInput").value.trim(),
    returned_action: $("actionInput").value.trim(),
    lesson: $("lessonInput").value.trim(),
    review_date: $("reviewDateInput").value,
    proof_artifact: $("proofInput").value.trim(),
    next_step: $("nextStepInput").value.trim()
  };
}

function fillDraft(d){
  lastDraft = d;
  $("titleInput").value = d.title || "";
  $("domainInput").value = d.domain || "";
  $("entityInput").value = d.entity || "";
  $("sourceTypeInput").value = d.source_type || "";
  $("tagsInput").value = (d.tags || []).join(", ");
  $("signalRoleInput").value = d.signal_role || "watch";
  $("confidenceInput").value = d.confidence || "Medium";
  $("actionabilityInput").value = d.actionability || "watch";
  $("cardTypeInput").value = d.card_type || "Watch Card";
  $("pullTriggerTypeInput").value = d.pull_trigger_type || "tag";
  $("relationshipTypeInput").value = d.relationship_type || "connects";
  $("signalInput").value = d.signal || "";
  $("interpretationInput").value = d.interpretation || "";
  $("trackableAsInput").value = d.trackable_as || "";
  $("trackingMetricInput").value = d.tracking_metric || "";
  $("baselineInput").value = d.baseline || "";
  $("targetInput").value = d.target_threshold || "";
  $("pullTriggerInput").value = d.pull_trigger || "";
  $("triggerInput").value = d.trigger_condition || "";
  $("resultToTrackInput").value = d.result_to_track || "";
  $("firstStepInput").value = d.first_step || "";
  $("impactMetricInput").value = d.impact_metric || "";
  $("feedbackInput").value = d.feedback_to_capture || "";
  $("relatedQueryInput").value = d.related_memory_query || "";
  $("patternInput").value = d.pattern || "";
  $("actionInput").value = d.returned_action || "";
  $("lessonInput").value = d.lesson || "";
  $("reviewDateInput").value = d.review_date || "";
  $("proofInput").value = d.proof_artifact || "";
  $("nextStepInput").value = d.next_step || "";
  $("draftPill").textContent = "draft ready";
  $("draftPill").className = "pill good";
}

function switchTab(tab){
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("active", p.id === tab));
  if(tab === "control") loadControl();
  if(tab === "source") loadSource();
  if(tab === "decisions") loadDecisions();
  if(tab === "memory") loadMemory();
  if(tab === "capture") loadCapture();
  if(tab === "changelog") loadChangelog();
}

document.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => switchTab(b.dataset.tab)));

async function queueForClaude(id, btn){
  const inQueue = /in queue|needs enrichment|queued/i.test(btn.textContent.trim());
  const newStatus = inQueue ? "codified" : "pending_claude";
  const res = await api(`/entries/${encodeURIComponent(id)}`, { method:"PATCH", body:JSON.stringify({ status:newStatus }) });
  const status = res.entry?.status || newStatus;
  const stillQueued = status === "pending_claude" || status === "raw" || status === "needs_enrichment";
  btn.textContent = status === "needs_enrichment" ? "Needs Enrichment" : (stillQueued ? "In Queue" : "Queue for Claude");
  btn.className = stillQueued ? "ghost small queue-active" : "ghost small";
  toast(stillQueued ? "Queued for Claude" : "Removed from queue");
  updateQueueBadge();
  loadControl();
  if($("queueList")) loadQueue();
}

async function updateQueueBadge(count){
  try{
    const n = count !== undefined ? count : (await api("/entries/queue")).count;
    const badge = $("queueBadge");
    if(!badge) return;
    badge.textContent = n;
    badge.classList.toggle("hidden", n === 0);
  } catch(_e){}
}

async function loadQueue(){
  const res = await api("/entries/queue");
  const entries = res.entries || [];
  const byDomain = {};
  entries.forEach(e => { const d = e.domain || "Other"; (byDomain[d] = byDomain[d] || []).push(e); });
  const domainStats = Object.entries(byDomain).sort((a,b)=>b[1].length-a[1].length).slice(0,4).map(([d, es]) => statHTML(d, es.length, "stat-queue")).join("");
  $("queueMeta").innerHTML = entries.length ? `${statHTML("Need Claude", entries.length, "stat-queue")}${domainStats}` : `<div class="item"><h3>Queue is empty</h3><p class="muted">Nothing is waiting for Claude right now.</p></div>`;
  $("queueList").innerHTML = entries.length ? entries.map(queueEntryHTML).join("") : `<div class="item"><h3>No queued entries</h3><p class="muted">Raw or partial entries you save will show up here until they are enriched.</p></div>`;
  updateQueueBadge(entries.length);
}

function pressureCard(item){
  return `<div class="item callout ${esc(item.level || "advisory")}"><h3>${esc(item.callout || "")}</h3><p class="muted">${esc(item.action || "")}</p>${item.count !== undefined ? `<div class="meta"><span class="tag">${esc(item.count)} items</span></div>` : ""}</div>`;
}

function recentEntryCard(e){
  const text = (e.interpretation || e.signal || e.raw_input || "").slice(0, 180);
  return `<div class="item">
    <h3>${esc(e.title || e.id)}</h3>
    <div class="meta"><span class="tag">${esc(e.domain)}</span><span class="tag">${esc(e.signal_role)}</span></div>
    <p class="muted">${esc(text)}</p>
  </div>`;
}

function recentImportCard(batch){
  const note = batch.status === "partial" ? (batch.notes || "Imported partially.") : `${fmtNumber(batch.projected_count)} records projected from ${fmtNumber(batch.row_count)} rows.`;
  return `<div class="item">
    <h3>${esc(batch.file_name)}</h3>
    <div class="meta"><span class="tag">${esc(batch.status)}</span><span class="tag">${esc(batch.sheet_count)} sheet${Number(batch.sheet_count) === 1 ? "" : "s"}</span></div>
    <p class="muted">${esc(note)}</p>
  </div>`;
}

function routingNoteCards(d, dormant){
  const checklist = (d.cockpit?.checklist || []).slice(0,4).map(x => compactItem("Routing note", x));
  const quality = [
    compactItem("Weak entries", `${fmtNumber(dormant.weak_entries?.length || 0)} signals still need stronger trackability.`),
    compactItem("Done without proof", `${fmtNumber(dormant.done_without_result?.length || 0)} actions were closed without a recorded result.`),
    compactItem("Review due", `${fmtNumber(dormant.review_due?.length || 0)} signals need review or refresh.`),
  ];
  $("routingNotes").innerHTML = checklist.join("") + compactItem("Go-around", d.cockpit?.go_around || "Reduce backlog before adding more noise.");
  $("qualityPanel").innerHTML = quality.join("") + ((dormant.weak_entries || []).slice(0, 2).map(e => recentEntryCard(e)).join(""));
}

async function loadControl(){
  const [d, actionsRes, queueRes, dormant] = await Promise.all([
    api("/command"),
    api("/actions?status=open&limit=8"),
    api("/entries/queue"),
    api("/command/dormant")
  ]);
  const queueCount = queueRes.count || 0;
  const headline = d.open_actions >= 25
    ? "Your system is generating more work than it is closing."
    : queueCount > 0
      ? "New reality is entering faster than it is being translated."
      : "The control plane is relatively quiet right now.";
  const subline = d.result_backlog > 0
    ? `${fmtNumber(d.result_backlog)} open actions still have no result logged. Close loops before adding more theory.`
    : "Use this page to see pressure, recent signals, and the actual next move.";
  $("controlHeadline").textContent = headline;
  $("controlSubline").textContent = subline;
  $("controlStats").innerHTML = [
    statHTML("Open actions", fmtNumber(d.open_actions)),
    statHTML("Completion rate", fmtPct(d.completion_rate)),
    statHTML("Queued for Claude", fmtNumber(queueCount), queueCount ? "stat-queue" : ""),
    statHTML("Imported rows", fmtNumber(d.import_rows || 0)),
    statHTML("Surfaced cards", fmtNumber(d.surfaced_open || 0)),
    statHTML("Result backlog", fmtNumber(d.result_backlog || 0)),
    statHTML("Watchlist items", fmtNumber(d.imported_watchlists || 0)),
    statHTML("Tracked signals", fmtNumber(d.total_entries || 0))
  ].join("");

  const pressure = [
    ...(d.cockpit?.warnings || []),
    ...(d.cockpit?.cautions || []),
    ...(d.cockpit?.advisories || [])
  ].slice(0, 8);
  $("systemPressure").innerHTML = pressure.length ? pressure.map(pressureCard).join("") : compactItem("Quiet", "No major warnings or cautions are active.");
  $("actionSnapshot").innerHTML = (actionsRes.actions || []).length ? actionsRes.actions.slice(0,6).map(actionHTML).join("") : compactItem("No open actions", "There is no returned-action backlog right now.");
  $("recentSignals").innerHTML = (d.recent || []).length ? d.recent.slice(0,6).map(recentEntryCard).join("") : compactItem("No recent signals", "Save a new entry to start building the control surface.");
  $("recentImports").innerHTML = (d.imports?.recent_batches || []).length ? d.imports.recent_batches.map(recentImportCard).join("") : compactItem("No imported source systems", "Use workbook import to add structured source data.");
  routingNoteCards(d, dormant);
  updateQueueBadge(queueCount);
}

function accountCard(a){
  return `<div class="item"><h3>${esc(a.account)}</h3><div class="meta"><span class="tag">${esc(fmtNumber(a.trades))} trades</span><span class="tag">${esc(fmtMoney(a.total_returns))}</span></div><p class="muted">Capital record imported from the accounting workbook.</p></div>`;
}

function watchlistCard(w){
  return `<div class="item"><h3>${esc(w.strategy_name)}</h3><div class="meta"><span class="tag">${esc(fmtNumber(w.item_count))} items</span><span class="tag">${esc(fmtNumber(w.sector_count))} sectors</span></div><p class="muted">Structured strategy sheet now visible as a source system.</p></div>`;
}

function devicePlaneCard(row){
  return `<div class="item"><h3>${esc(row.sheet_name)}</h3><div class="meta"><span class="tag">${esc(row.parser_status)}</span><span class="tag">${esc(fmtNumber(row.size_bytes || 0))} bytes</span></div><p class="muted">${esc(row.notes || "Binary workbook manifest imported.")}</p></div>`;
}

function tradeCard(t){
  const price = t.avg_price ? `avg ${t.avg_price}` : "avg n/a";
  const sell = t.sell_price ? `sell ${t.sell_price}` : "sell n/a";
  const pnl = t.returns_amount !== null && t.returns_amount !== undefined ? fmtMoney(t.returns_amount) : "n/a";
  return `<div class="item"><h3>${esc(t.symbol || "Unknown trade")}</h3><div class="meta"><span class="tag">${esc(t.account || "Unknown account")}</span><span class="tag">${esc(t.trade_date_text || "date n/a")}</span><span class="tag">${esc(pnl)}</span></div><p class="muted">${esc(`${price} · ${sell} · ${t.shares || 0} shares`)}</p></div>`;
}

function setupCard(s){
  const trigger = s.trigger_price !== null && s.trigger_price !== undefined ? s.trigger_price : "n/a";
  const pct = s.pct_change !== null && s.pct_change !== undefined ? `${Number(s.pct_change).toFixed(2)}%` : "n/a";
  return `<div class="item"><h3>${esc(s.symbol || "Unknown setup")}</h3><div class="meta"><span class="tag">${esc(s.calc_type || "setup")}</span><span class="tag">${esc(pct)}</span></div><p class="muted">${esc(`avg ${s.avg_price || "n/a"} · trigger ${trigger} · ${s.shares || 0} shares`)}</p></div>`;
}

function watchlistItemCard(w){
  const name = w.ticker || w.display_name || "Watchlist item";
  const signals = [w.sector, w.industry, w.catalyst].filter(Boolean).slice(0,2);
  const price = w.price !== null && w.price !== undefined ? `price ${w.price}` : "price n/a";
  return `<div class="item"><h3>${esc(name)}</h3><div class="meta">${signals.map(s=>`<span class="tag">${esc(s)}</span>`).join("")}</div><p class="muted">${esc(`${price}${w.note ? " · " + w.note.slice(0, 90) : ""}`)}</p></div>`;
}

function importLedgerCard(batch){
  return `<div class="item">
    <h3>${esc(batch.file_name)}</h3>
    <div class="meta"><span class="tag">${esc(batch.status)}</span><span class="tag">${esc(batch.sheet_count)} sheets</span><span class="tag">${esc(batch.projected_count)} projected</span></div>
    <p class="muted">${esc(batch.notes || "Structured source data imported successfully.")}</p>
  </div>`;
}

async function loadSource(){
  const data = await api("/source-data");
  const s = data.summary || {};
  $("sourceStats").innerHTML = [
    statHTML("Import batches", fmtNumber(s.batches || 0)),
    statHTML("Trades", fmtNumber(s.portfolio_trades || 0)),
    statHTML("Setups", fmtNumber(s.risk_reward_setups || 0)),
    statHTML("Watchlists", fmtNumber(s.watchlists || 0)),
    statHTML("Watchlist items", fmtNumber(s.watchlist_items || 0)),
    statHTML("Device planes", fmtNumber(s.device_log_planes || 0)),
    statHTML("Raw rows", fmtNumber(s.raw_rows || 0)),
    statHTML("Partial imports", fmtNumber(s.partial_batches || 0))
  ].join("");
  $("accountSummary").innerHTML = (data.trading_accounts || []).length ? data.trading_accounts.map(accountCard).join("") : compactItem("No account data", "No structured trading accounts have been imported.");
  $("watchlistSummary").innerHTML = (data.watchlist_rollup || []).length ? data.watchlist_rollup.map(watchlistCard).join("") : compactItem("No watchlists", "No strategy sheets are loaded yet.");
  $("deviceSummary").innerHTML = (data.device_planes || []).length ? data.device_planes.slice(0,6).map(devicePlaneCard).join("") : compactItem("No device planes", "No binary parser workbook has been imported.");
  $("tradeTable").innerHTML = (data.trades || []).length ? data.trades.map(tradeCard).join("") : compactItem("No trades", "No portfolio trade records are available.");
  $("setupTable").innerHTML = (data.setups || []).length ? data.setups.map(setupCard).join("") : compactItem("No setups", "No risk / reward setups are available.");
  $("watchlistItems").innerHTML = (data.watchlist_items || []).length ? data.watchlist_items.slice(0,16).map(watchlistItemCard).join("") : compactItem("No watchlist items", "No structured watchlist rows are loaded.");
  $("importLedger").innerHTML = (s.recent_batches || []).length ? s.recent_batches.map(importLedgerCard).join("") : compactItem("No imports yet", "The import ledger is empty.");
}

async function loadDecisions(){
  const [actionsRes, d] = await Promise.all([
    api("/actions?status=open&limit=100"),
    api("/command")
  ]);
  $("decisionStats").innerHTML = [
    statHTML("Open actions", fmtNumber(d.open_actions || 0)),
    statHTML("Result backlog", fmtNumber(d.result_backlog || 0)),
    statHTML("Surfaced cards", fmtNumber(d.surfaced_open || 0)),
    statHTML("Investing action load", fmtNumber((d.domain_action_load || []).find(x=>x.domain==="Investing")?.open_actions || 0))
  ].join("");
  $("actionsList").innerHTML = (actionsRes.actions || []).length ? actionsRes.actions.map(actionHTML).join("") : compactItem("No open actions", "There is no active execution backlog.");
  if(!$("quickActionsList").innerHTML.trim()){
    $("quickActionsList").innerHTML = compactItem("Ready", "Ask a routing question above to pull immediate moves from the database.");
  }
  if(!$("bigActionsList").innerHTML.trim()){
    $("bigActionsList").innerHTML = compactItem("Ready", "System-level routing suggestions will appear here after a pull query.");
  }
}

async function loadMemory(){
  const q = encodeURIComponent($("searchInput").value.trim());
  const d = encodeURIComponent($("filterDomain").value);
  const res = await api(`/entries?q=${q}&domain=${d}&limit=100`);
  $("memoryList").innerHTML = res.entries.length ? res.entries.map(entryHTML).join("") : compactItem("No matching entries", "Try a different search or save a new entry.");
}

async function loadCapture(){
  await Promise.all([loadQueue(), checkAiStatus()]);
}

async function loadChangelog(){
  const res = await api("/versions");
  const versions = (res.versions || []).slice().reverse();
  const current = res.current || "";
  const totalFeatures = versions.reduce((n, v) => n + (v.features || []).length, 0);
  $("changelogMeta").textContent = `${versions.length} versions · ${totalFeatures} shipped features · ${current}`;
  $("changelogList").innerHTML = versions.map(v => changelogEntryHTML(v, current)).join("");
}

async function codify(){
  const base = collectBase();
  if(!base.raw_input){ toast("Paste raw input first"); return; }
  const btn = $("codifyBtn");
  const original = btn.textContent;
  btn.textContent = "Translating...";
  btn.disabled = true;
  try{
    const res = await api("/translate/ai", { method:"POST", body:JSON.stringify(base) });
    fillDraft(res.draft);
    toast(res.ai_used ? "AI signal translation complete" : "Signal translated");
  } finally {
    btn.textContent = original;
    btn.disabled = false;
  }
}

async function loopAnalyze(){
  const base = collectBase();
  if(!base.raw_input){ toast("Paste raw input first"); return; }
  const res = await api("/loop/analyze", { method:"POST", body:JSON.stringify(base) });
  const d = res.database_json;
  d.qa_scores = res.qa_scores;
  fillDraft(d);
  const scores = Object.entries(res.qa_scores || {}).map(([k,v])=>`<span class="tag">${esc(k)} ${esc(v)}</span>`).join("");
  const trace = (res.loop_trace || []).map(x => `<div class="kv"><b>Loop ${esc(x.loop)}</b><span>${esc(x.plan)}</span></div>`).join("");
  $("saveOutput").innerHTML = `<div class="item"><h3>${esc(res.outcome)}</h3><div class="meta">${scores}</div>${trace}</div>`;
  toast("Loop analysis complete");
}

function cardHTML(c){
  const action = meaningfulActionText(c.action);
  const track = meaningfulMetricText(c.track);
  const next = meaningfulStepText(c.next_step);
  return `<div class="item">
    <h3>${esc(c.source_title || c.source_entry_id)}</h3>
    <div class="meta"><span class="tag">${esc(c.card_type || "Action Card")}</span><span class="tag">score ${esc(c.score)}</span></div>
    <div class="kv"><b>Why</b><span>${esc(c.why_resurfaced)}</span></div>
    ${kvHTML("Action", action)}
    ${kvHTML("Track", track)}
    ${kvHTML("Next", next)}
  </div>`;
}

async function save(){
  const payload = collectDraft();
  if(!payload.raw_input){ toast("Paste raw input first"); return; }
  if(!payload.signal && !payload.interpretation) payload.status = "pending_claude";
  const res = await api("/entries", { method:"POST", body:JSON.stringify(payload) });
  const cards = res.context_packet?.cards || [];
  if(res.entry?.status === "pending_claude"){
    $("saveOutput").innerHTML = `<div class="item"><h3>Queued: ${esc(res.entry_id)}</h3><p class="muted">Saved to memory and added to the Claude queue.</p></div>`;
    toast("Saved — queued for Claude");
  } else if(res.entry?.status === "needs_enrichment"){
    $("saveOutput").innerHTML = `<div class="item"><h3>Needs Enrichment: ${esc(res.entry_id)}</h3><p class="muted">Saved, but still too weak to trust without enrichment.</p></div>`;
    toast("Saved — needs enrichment");
  } else {
    $("saveOutput").innerHTML = `<div class="item"><h3>Saved: ${esc(res.entry_id)}</h3><p class="muted">Created ${res.pull_rules?.length || 0} pull rules and returned ${cards.length} context cards.</p></div>${cards.map(cardHTML).join("")}`;
    toast("Saved to memory");
  }
  loadControl();
  loadQueue();
}

async function pullMemory(){
  const raw = $("pullInput").value.trim();
  if(!raw){ toast("Enter a routing query"); return; }
  const res = await api("/pull", { method:"POST", body:JSON.stringify({ query:raw, domain:$("pullDomain").value }) });
  const quick = res.quick_actions || [];
  const big = res.big_picture_actions || [];
  if(res.no_match){
    $("quickActionsList").innerHTML = compactItem("No actionable memory", res.no_match.message || "Nothing strong matched this query.");
    $("bigActionsList").innerHTML = compactItem("Quiet engine", `No strong system-level move matched "${raw}".`);
    toast("No actionable memory matched");
    return;
  }
  $("quickActionsList").innerHTML = quick.length ? quick.map(pamaCardHTML).join("") : compactItem("No quick actions", "No immediate move matched this query.");
  $("bigActionsList").innerHTML = big.length ? big.map(pamaCardHTML).join("") : compactItem("No system moves", "No broader routing move matched this query.");
  toast(`Pulled ${quick.length + big.length} routing signals`);
}

async function dismissSignal(entryId){
  const reason = prompt("Why dismiss this signal?");
  if(!reason) return;
  await api(`/entries/${entryId}`, { method:"PATCH", body:JSON.stringify({ action_status:"cancelled", status:"archived", result:`Dismissed from pull: ${reason}` }) });
  toast("Signal dismissed");
  pullMemory();
  loadControl();
  loadDecisions();
}

async function actOnSignal(entryId, actionTitle){
  if(!confirm(`Do the action first, then log the result.\n\n${actionTitle ? `Action: ${actionTitle}` : ""}`)) return;
  const result = prompt("What result or proof did this produce?");
  if(!result) return;
  await api(`/entries/${entryId}`, { method:"PATCH", body:JSON.stringify({ action_status:"done", result, status:"validated" }) });
  toast("Result logged");
  pullMemory();
  loadControl();
  loadDecisions();
}

async function recontextualizeSignal(entryId){
  const instruction = prompt("How should this signal be re-translated?");
  if(!instruction) return;
  await api(`/entries/${entryId}/recategorize`, { method:"POST", body:JSON.stringify({ instruction }) });
  toast("Signal re-translated");
  pullMemory();
  loadControl();
  loadMemory();
}

async function markDone(id){
  const result = prompt("Result / proof from this action?") || "done";
  await api(`/actions/${id}`, { method:"PATCH", body:JSON.stringify({ status:"done", result }) });
  toast("Action marked done");
  loadControl();
  loadDecisions();
}

async function extractPatternFromAction(actionId, entryId){
  const instruction = prompt("What reusable rule or pattern did this action reveal?");
  if(!instruction) return;
  if(entryId){
    await api(`/entries/${entryId}/recategorize`, { method:"POST", body:JSON.stringify({ instruction:`Extract this returned action into a reusable pattern: ${instruction}`, tags:["pattern","extracted-action"] }) });
  }
  await api(`/actions/${actionId}`, { method:"PATCH", body:JSON.stringify({ status:"waiting", lesson_update:`Pattern extracted: ${instruction}` }) });
  toast("Pattern extracted");
  loadControl();
  loadDecisions();
}

async function abortAction(id){
  const reason = prompt("Why abort this action?");
  if(!reason) return;
  await api(`/actions/${id}`, { method:"PATCH", body:JSON.stringify({ status:"cancelled", result:`Aborted: ${reason}` }) });
  toast("Action aborted");
  loadControl();
  loadDecisions();
}

async function checkAiStatus(){
  try{
    const s = await api("/ai/status");
    const note = $("aiStatusNote");
    if(s.ai_enabled){
      note.className = "ai-status-note ai-status-on";
      note.innerHTML = `<span class="ai-dot on"></span>AI translation active — Claude Opus 4.8`;
    } else {
      note.className = "ai-status-note ai-status-off";
      note.innerHTML = `<span class="ai-dot off"></span>AI translation inactive — <code>${esc(s.hint || "Set ANTHROPIC_API_KEY before starting the server")}</code>`;
    }
  } catch(_e){}
}

$("saveBtn").addEventListener("click", save);
$("codifyBtn").addEventListener("click", codify);
$("loopBtn").addEventListener("click", loopAnalyze);
$("pullBtn").addEventListener("click", pullMemory);
$("refreshControl").addEventListener("click", loadControl);
$("refreshSource").addEventListener("click", loadSource);
$("refreshDecisions").addEventListener("click", loadDecisions);
$("refreshMemory").addEventListener("click", loadMemory);
$("refreshQueue").addEventListener("click", loadQueue);
$("refreshChangelog").addEventListener("click", loadChangelog);
$("searchInput").addEventListener("input", ()=>{ clearTimeout(window.__searchTimer); window.__searchTimer = setTimeout(loadMemory, 250); });
$("filterDomain").addEventListener("change", loadMemory);
$("clearBtn").addEventListener("click", ()=>{
  document.querySelectorAll("textarea,input").forEach(el => { if(el.id !== "searchInput") el.value = ""; });
  document.querySelectorAll("select").forEach(el => { if(el.id !== "filterDomain") el.selectedIndex = 0; });
  $("draftPill").textContent = "empty";
  $("draftPill").className = "pill muted";
  $("saveOutput").innerHTML = "";
});
$("exportBtn").addEventListener("click", ()=>{ window.location.href = "/api/export"; });

loadControl();
loadDecisions();
updateQueueBadge();
