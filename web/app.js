const API = "/api";
const $ = id => document.getElementById(id);
const esc = v => String(v ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;");
const tagsFrom = s => String(s||"").split(/[#,]/).map(x=>x.trim().toLowerCase()).filter(Boolean).filter((x,i,a)=>a.indexOf(x)===i);
let lastDraft = null;
let lastStockIntel = null;
const INNBANK_QUESTIONS = [
  "What value is being created?",
  "Where is money flowing?",
  "What data is being generated?",
  "What resources do I control?",
  "What projects are active?",
  "What systems are producing results?",
  "What bottlenecks need action?",
  "Where should capital, time, tools, or attention be routed next?",
];
const DATA_PLANES = [
  { name:"Money Data Plane", tracks:"income, expenses, cashflow, savings, debt, investments", domains:["Personal Finance","Investing"] },
  { name:"Sales Data Plane", tracks:"listings, inventory, buyers, offers, sold comps, margins", domains:["Business"] },
  { name:"Career Data Plane", tracks:"skills, job posts, resume proof, work reps, projects", domains:["Career"] },
  { name:"Lab/Work Data Plane", tracks:"sessions, QA/QC, operators, SOPs, bottlenecks, task issues", domains:["Lab"] },
  { name:"Portfolio Data Plane", tracks:"stocks, filings, watchlists, theses, catalysts, decisions", domains:["Investing"] },
  { name:"Learning Data Plane", tracks:"Network+, notes, mock questions, concepts, weak areas", domains:["Network+"] },
  { name:"Fitness Data Plane", tracks:"weight, measurements, workouts, reps, fatigue, growth signals", domains:["Fitness"] },
  { name:"Automation Data Plane", tracks:"workflows, scripts, dashboards, AI outputs, repeatable tasks", domains:["AI Project"] },
  { name:"Relationship/Network Data Plane", tracks:"contacts, opportunities, follow-ups, trust, collaboration", domains:["Business","Career"] },
];
const SUB_CONTROL_PLANES = [
  { name:"Sales OS", function:"Turns products and value into cash.", domains:["Business"] },
  { name:"Capital Allocator OS", function:"Routes money to bills, savings, investments, tools, and projects.", domains:["Personal Finance","Investing"] },
  { name:"Info Analyzer OS", function:"Turns raw data into intelligence and memory.", domains:["AI Project","Lab","Business","Investing","Network+"] },
  { name:"Portfolio Desk", function:"Tracks investing theses, watchlists, trades, and signals.", domains:["Investing"] },
  { name:"Lab Ops Dashboard", function:"Tracks work systems, QA/QC, operators, and SOPs.", domains:["Lab"] },
  { name:"Skill/Career OS", function:"Converts reps and projects into career proof.", domains:["Career","Network+","Lab"] },
  { name:"Fitness OS", function:"Tracks body data and workout effectiveness.", domains:["Fitness"] },
  { name:"Automation OS", function:"Turns repeated workflows into scalable systems.", domains:["AI Project"] },
  { name:"Project OS", function:"Tracks builds, experiments, tools, and shipped artifacts.", domains:["AI Project","Lab"] },
];

async function api(path, opts={}){
  const res = await fetch(API + path, { ...opts, headers:{"Content-Type":"application/json", ...(opts.headers||{})} });
  const txt = await res.text();
  const data = txt ? JSON.parse(txt) : {};
  if(!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
function toast(msg){ const t=$("toast"); t.textContent=msg; t.classList.remove("hidden"); setTimeout(()=>t.classList.add("hidden"),2500); }
function countMap(rows, valueKey="count"){
  const out = {};
  (rows || []).forEach(row => { out[row.domain] = Number(row[valueKey] || 0); });
  return out;
}
function sumDomains(map, domains){
  return (domains || []).reduce((n, domain) => n + Number(map[domain] || 0), 0);
}
function innbankMetric(value, label){
  return `<div class="inn-metric"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`;
}
function renderInnbankArchitecture(d){
  const el = $("innbankArchitecture");
  if(!el) return;
  el.innerHTML = `
    <div class="item inn-stack">
      <p class="eyebrow">Mission Engine</p>
      <h3>INNBANK</h3>
      <p class="muted">Create, capture, route, and multiply value.</p>
      <div class="inn-metrics">
        ${innbankMetric(d.total_entries, "tracked signals")}
        ${innbankMetric(d.open_actions, "active routes")}
        ${innbankMetric(d.completed_actions, "closed loops")}
      </div>
    </div>
    <div class="item inn-stack">
      <p class="eyebrow">Ultimate Control Plane</p>
      <h3>INNBANK Command Center</h3>
      <p class="muted">See everything, route resources, track performance, and make better decisions.</p>
      <p class="muted">Reality produces data. Data feeds dashboards. Dashboards reveal signals. Signals guide decisions. Decisions route capital. Capital funds action. Action creates more value and more data.</p>
    </div>
    <div class="item inn-stack">
      <p class="eyebrow">Core Flywheel</p>
      <h3>Value Creation → Cashflow → Resources → Data → Intelligence → Better Decisions → Better Systems → More Value Creation</h3>
      <p class="muted">The control plane exists to keep this flywheel compounding instead of leaking energy into backlog, noise, or un-routed effort.</p>
    </div>`;
}
function renderInnbankQuestions(){
  const el = $("innbankQuestions");
  if(!el) return;
  el.innerHTML = INNBANK_QUESTIONS.map((q, i) => `<div class="item question-card"><span class="pill muted">Q${i+1}</span><p>${esc(q)}</p></div>`).join("");
}
function renderPlaneCards(targetId, items, domainCounts, actionCounts){
  const el = $(targetId);
  if(!el) return;
  el.innerHTML = items.map(item => {
    const signals = sumDomains(domainCounts, item.domains);
    const actions = sumDomains(actionCounts, item.domains);
    return `<div class="item plane-card">
      <div class="plane-head">
        <div>
          <h3>${esc(item.name)}</h3>
          <p class="muted">${esc(item.tracks || item.function || "")}</p>
        </div>
        <span class="pill">${esc(item.domains.join(" + "))}</span>
      </div>
      <div class="inn-metrics">
        ${innbankMetric(signals, "signals")}
        ${innbankMetric(actions, "active routes")}
      </div>
      </div>`;
  }).join("");
}
function renderImportPlanes(imports){
  const el = $("importPlanes");
  if(!el) return;
  const sources = imports?.sources || [];
  const recent = imports?.recent_batches || [];
  if(!sources.length && !recent.length){
    el.innerHTML = `<div class="item"><h3>No imported source systems</h3><p class="muted">Use the workbook import API or CLI to load external spreadsheets into dedicated SQLite tables.</p></div>`;
    return;
  }
  const sourceCards = sources.map(source => `<div class="item">
    <h3>${esc(source.label)}</h3>
    <div class="meta"><span class="tag">${esc(source.count)}</span></div>
    <p class="muted">${esc(source.detail)}</p>
  </div>`).join("");
  const recentCards = recent.length ? `<div class="item"><h3>Recent Imports</h3><p class="muted">${recent.map(batch => `${batch.file_name} (${batch.status})`).join(" • ")}</p></div>` : "";
  el.innerHTML = sourceCards + recentCards;
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
    "archive as raw context unless a future trigger makes it actionable.",
    "compare against the old thesis and update confidence with evidence.",
  ].includes(t) || /^(review the command surface|execute, then log result back into the db|click track signal)/.test(t);
}
function looksGenericMetric(value){
  const t = normText(value);
  return !t || [
    "entries saved, relevant pulls, action cards executed, false pulls reduced",
    "define metric or observable",
    "observable result",
    "accepted, ignored, or rejected when resurfaced in relevant context",
    "number of useful future links or decisions improved by this reference",
    "number of repeats and domains where it appears",
    "confidence before/after and evidence that changed it",
    "artifact created and result produced",
    "depends on document/headline content",
    "ir press releases, earnings transcripts, guidance language",
  ].includes(t);
}
function looksGenericWhy(value){
  const t = normText(value);
  return !t || [
    "this memory matched the query and can return a decision or action.",
    "this action came from a translated signal.",
    "signal returned an action.",
  ].includes(t);
}
function looksGenericFirstStep(value){
  const t = normText(value);
  return !t || [
    "open the entry, execute the returned action, and log the result.",
    "save, retrieve related memories, execute/track action, then log result.",
    "add this as a test entry, run retrieval/contextualization, and record whether the returned action was useful.",
    "create one ledger row with thesis, allocation rule, tracking metric, review date, and result field.",
    "review the command surface, execute the action, then log the result.",
    "execute, then log result back into the db.",
    "click track signal or archive the item.",
    "set next filing or review date.",
    "run cash quality, balance sheet, or risk drill.",
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
function meaningfulStepText(value){
  const text = String(value || "").trim();
  return looksGenericFirstStep(text) ? "" : text;
}
function meaningfulMetricText(value){
  const text = String(value || "").trim();
  return looksGenericMetric(text) ? "" : text;
}
function kvHTML(label, value){
  return value ? `<div class="kv"><b>${esc(label)}</b><span>${esc(value)}</span></div>` : "";
}
function switchTab(tab){
  document.querySelectorAll(".tab").forEach(b=>b.classList.toggle("active", b.dataset.tab===tab));
  document.querySelectorAll(".panel").forEach(p=>p.classList.toggle("active", p.id===tab));
  if(tab==="command") loadCommand();
  if(tab==="queue") loadQueue();
  if(tab==="stock") loadStockIntel();
  if(tab==="memory") loadMemory();
  if(tab==="actions") loadActions();
  if(tab==="patterns") loadPatterns();
  if(tab==="changelog") loadChangelog();
}

document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>switchTab(b.dataset.tab)));

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

function cardHTML(c){
  const action = meaningfulActionText(c.action);
  const track = meaningfulMetricText(c.track);
  const next = meaningfulStepText(c.next_step);
  return `<div class="item">
    <h3>${esc(c.source_title || c.source_entry_id)}</h3>
    <div class="meta"><span class="tag">${esc(c.card_type || "Action Card")}</span><span class="tag">${esc(c.actionability || "watch")}</span><span class="tag">score ${esc(c.score)}</span><span class="tag">${esc(c.relationship_suggestion || "connects")}</span></div>
    <div class="kv"><b>Why</b><span>${esc(c.why_resurfaced)}</span></div>
    ${kvHTML("Action", action)}
    ${kvHTML("Track", track)}
    <div class="kv"><b>Trigger</b><span>${esc(c.pull_trigger || "")}</span></div>
    <div class="kv"><b>Decision</b><span>${esc(c.decision_update)}</span></div>
    ${kvHTML("Next", next)}
  </div>`;
}
function enrichBadge(e){
  const s = e.status || "";
  const hasAI = !!(e.interpretation && e.interpretation.trim());
  const isChild = !!(e.parent_entry_id && e.parent_entry_id.trim());
  if(s === "pending_claude" || s === "raw") return `<span class="enrich-badge eb-queued">⬦ Queued</span>`;
  if(s === "needs_enrichment") return `<span class="enrich-badge eb-needs">◈ Needs Enrichment</span>`;
  if(isChild) return `<span class="enrich-badge eb-child">↑ Extracted</span>`;
  if(hasAI) return `<span class="enrich-badge eb-enriched">◆ AI Enriched</span>`;
  return `<span class="enrich-badge eb-raw">◇ Codified</span>`;
}
function entryHTML(e){
  const inQueue = e.status === "pending_claude" || e.status === "raw" || e.status === "needs_enrichment";
  const queueLabel = e.status === "needs_enrichment" ? "Needs Enrichment" : (inQueue ? "In Queue" : "Queue for Claude");
  const queueClass = inQueue ? "ghost small queue-active" : "ghost small";
  const badge = enrichBadge(e);
  const chip = e.metadata?.contextual_memory || null;
  const interp = (e.interpretation || "").trim();
  const lesson = meaningfulLesson(e);
  const action = meaningfulAction(e);
  const firstStep = meaningfulFirstStep(e);
  const metric = meaningfulMetric(e);
  const chipHTML = chip ? `
    <div class="item">
      <div class="meta">
        <span class="tag">Memory Chip</span>
        <span class="tag">${esc(chip.context_role || "context")}</span>
        <span class="tag">${esc(chip.right_context || "")}</span>
      </div>
      ${kvHTML("Capture", chip.capture || "")}
      ${kvHTML("Reuse", chip.reuse?.action || chip.synthesized_action || "")}
      ${kvHTML("Compound", (chip.compound?.related_titles || []).filter(Boolean).slice(0,3).join(" • "))}
    </div>` : "";
  return `<div class="item${inQueue?' item-queued':''}">
    <div class="entry-top">${badge}<h3>${esc(e.title || e.id)}</h3></div>
    <div class="meta"><span class="tag">${esc(e.domain)}</span><span class="tag">${esc(e.signal_role)}</span><span class="tag">${esc(e.actionability || "")}</span>${(e.tags||[]).slice(0,5).map(t=>`<span class="tag">${esc(t)}</span>`).join("")}</div>
    ${interp ? `<p class="entry-interp">${esc(interp.slice(0,220))}</p>` : `<p class="muted">${esc((e.signal || e.raw_input || "").slice(0,220))}</p>`}
    ${chipHTML}
    ${kvHTML("Lesson", lesson ? lesson.slice(0,160) : "")}
    ${kvHTML("Action", action)}
    ${kvHTML("First Step", firstStep)}
    ${kvHTML("Metric", metric)}
    <div class="buttons compact" style="margin-top:10px">
      <button class="${queueClass}" onclick="queueForClaude('${esc(e.id)}', this)">${queueLabel}</button>
    </div>
  </div>`;
}
async function queueForClaude(id, btn){
  const inQueue = btn.textContent.trim() === "In Queue" || btn.textContent.trim() === "Needs Enrichment";
  const newStatus = inQueue ? "codified" : "pending_claude";
  try {
    const res = await api(`/entries/${encodeURIComponent(id)}`, {method:"PATCH", body:JSON.stringify({status: newStatus})});
    const status = res.entry?.status || newStatus;
    const stillQueued = status === "pending_claude" || status === "raw" || status === "needs_enrichment";
    btn.textContent = status === "needs_enrichment" ? "Needs Enrichment" : (stillQueued ? "In Queue" : "Queue for Claude");
    btn.className = stillQueued ? "ghost small queue-active" : "ghost small";
    btn.closest(".item").classList.toggle("item-queued", stillQueued);
    toast(status === "needs_enrichment" ? "Still needs enrichment" : (stillQueued ? "Queued for Claude" : "Removed from queue"));
    updateQueueBadge();
    loadCommand();
  } catch(err){ toast("Error: " + err.message); }
}
function queueEntryHTML(e){
  const age = e.created_at ? e.created_at.slice(0,10) : "";
  const badge = e.status === "needs_enrichment" ? "◈ Needs Enrichment" : "⬦ Queued";
  const buttonLabel = e.status === "needs_enrichment" ? "Needs Enrichment" : "In Queue";
  return `<div class="item item-queued">
    <div class="entry-top"><span class="enrich-badge ${e.status === "needs_enrichment" ? "eb-needs" : "eb-queued"}">${badge}</span><h3>${esc(e.title || e.id)}</h3></div>
    <div class="meta">
      <span class="tag">${esc(e.domain)}</span>
      ${e.entity ? `<span class="tag">${esc(e.entity)}</span>` : ""}
      ${age ? `<span class="tag muted">${esc(age)}</span>` : ""}
      <span class="tag muted">${esc(String((e.raw_input||"").split(/\s+/).length))} words</span>
    </div>
    <p class="muted">${esc((e.raw_input || "").slice(0, 300))}</p>
    <div class="buttons compact" style="margin-top:10px">
      <button class="ghost small queue-active" onclick="queueForClaude('${esc(e.id)}', this)">${buttonLabel}</button>
    </div>
  </div>`;
}
async function loadQueue(){
  const res = await api("/entries/queue");
  const entries = res.entries || [];
  const byDomain = {};
  entries.forEach(e => { const d = e.domain||"Other"; (byDomain[d]=byDomain[d]||[]).push(e); });
  const domainStats = Object.entries(byDomain)
    .sort((a,b)=>b[1].length-a[1].length)
    .map(([d,es])=>`<div class="stat stat-queue"><strong>${esc(es.length)}</strong><span class="muted">${esc(d)}</span></div>`)
    .join("");
  $("queueMeta").innerHTML = entries.length
    ? `<div class="stat stat-queue"><strong>${esc(entries.length)}</strong><span class="muted">Need Claude</span></div>${domainStats}`
    : `<p class="muted" style="margin:0">Queue is empty.</p>`;
  $("queueList").innerHTML = entries.length
    ? entries.map(queueEntryHTML).join("")
    : `<div class="item"><h3>Queue is empty</h3><p class="muted">Save entries from the New Entry tab. Partial or generic entries land here automatically until Claude enriches them.</p></div>`;
  updateQueueBadge(entries.length);
}
async function updateQueueBadge(count){
  try {
    const n = count !== undefined ? count : (await api("/entries/queue")).count;
    const badge = $("queueBadge");
    if(!badge) return;
    badge.textContent = n;
    badge.classList.toggle("hidden", n === 0);
  } catch(e){}
}
function actionHTML(a){
  const card = a.execution_card || {};
  const steps = (card.exact_actions || []).map(s=>`<li>${esc(s)}</li>`).join("");
  const why = meaningfulWhy(card.why_it_matters || a.why || "");
  const track = meaningfulMetricText(card.track || a.track_metric || "");
  const doneBtn = a.status !== "done" ? `<button class="ghost small" onclick="markDone('${esc(a.id)}')">Mark Done</button>` : "";
  const recatBtn = `<button class="ghost small" onclick="extractPatternFromAction('${esc(a.id)}','${esc(a.entry_id)}')">Recategorize</button>`;
  const abortBtn = a.status !== "cancelled" ? `<button class="ghost small danger-btn" onclick="abortAction('${esc(a.id)}')">Abort</button>` : "";
  return `<div class="item action-card">
    <h3>${esc(card.action_name || a.action_title)}</h3>
    <div class="meta"><span class="tag">${esc(card.card_type || "Action Card")}</span><span class="tag">${esc(a.priority)}</span><span class="tag">${esc(a.status)}</span>${a.due_date?`<span class="tag">due ${esc(a.due_date)}</span>`:""}</div>
    <div class="kv"><b>Source</b><span>${esc(card.source || a.source_title || a.entry_id)}</span></div>
    ${kvHTML("Why it matters", why)}
    <div class="kv"><b>Exact actions</b><span><ol class="steps">${steps}</ol></span></div>
    ${kvHTML("Track", track)}
    <div class="kv"><b>Abort rule</b><span>${esc(card.abort_prompt || "Abort if the action no longer changes a decision or result.")}</span></div>
    <div class="buttons">${doneBtn}${recatBtn}${abortBtn}</div>
  </div>`;
}
function dormantEntryHTML(e){
  return `<div class="item">
    <h3>${esc(e.title || e.id)}</h3>
    <div class="meta"><span class="tag">${esc(e.domain || "Other")}</span><span class="tag">${esc(e.signal_role || "watch")}</span></div>
    <p class="muted">${esc(e.signal || e.raw_input || "").slice(0,220)}</p>
    <div class="kv"><b>Missing</b><span>${[
      !e.trackable_as ? "trackable as" : "",
      !e.tracking_metric ? "tracking metric" : "",
      !e.returned_action ? "returned action" : "",
      (!e.trigger_condition && !e.review_date && !e.pull_trigger) ? "trigger/review date" : "",
      !e.actionability ? "actionability" : "",
      !e.card_type ? "card type" : "",
      !e.result_to_track ? "result loop" : ""
    ].filter(Boolean).join(", ")}</span></div>
    <div class="buttons">
      <button class="ghost small" onclick="recategorizeEntry('${esc(e.id)}')">Recategorize</button>
      <button class="ghost small danger-btn" onclick="deleteEntry('${esc(e.id)}')">Delete</button>
    </div>
  </div>`;
}
function calloutHTML(c){
  const buttons = (c.buttons || []).map(btn => `
      <button class="${btn.action === "clear_surfaced" ? "ghost small danger-btn" : "ghost small"}" onclick="runCockpitAction('${esc(btn.action)}','${esc(btn.value || "")}')">${esc(btn.label || "Open")}</button>
    `).join("");
  return `<div class="item callout ${esc(c.level || "advisory")}">
    <h3>${esc(c.callout || "")}</h3>
    <p class="muted">${esc(c.action || "")}</p>
    ${c.count!==undefined?`<span class="tag">${esc(c.count)} item${Number(c.count)===1?"":"s"}</span>`:""}
    ${buttons ? `<div class="buttons compact callout-actions">${buttons}</div>` : ""}
  </div>`;
}
async function runCockpitAction(action, value){
  if(action === "show_actions"){
    switchTab("actions");
    await loadActions();
    toast("Opened action queue");
    return;
  }
  if(action === "show_queue"){
    switchTab("queue");
    await loadQueue();
    toast("Opened translation queue");
    return;
  }
  if(action === "show_dump"){
    switchTab("dump");
    $("rawInput")?.focus();
    return;
  }
  if(action === "show_memory"){
    switchTab("memory");
    if(value && $("searchInput")) $("searchInput").value = value;
    await loadMemory();
    toast("Opened memory ledger");
    return;
  }
  if(action === "detect_dormant"){
    await loadDormant();
    $("dormantList")?.scrollIntoView({behavior:"smooth", block:"start"});
    toast("Bottlenecks detected");
    return;
  }
  if(action === "rewire_memory"){
    await rewireMemory();
    return;
  }
  if(action === "run_patterns"){
    switchTab("patterns");
    await runPatternEngine();
    return;
  }
  if(action === "focus_pull"){
    $("pullInput")?.focus();
    $("pullInput")?.scrollIntoView({behavior:"smooth", block:"center"});
    return;
  }
  if(action === "pull_query"){
    if(value && $("pullInput")) $("pullInput").value = value;
    await pullMemory();
    return;
  }
  if(action === "clear_surfaced"){
    if(!confirm("Archive all open surfaced memory cards? This keeps the source entries but clears stale cockpit cards.")) return;
    const res = await api("/surfaced-cards/clear", {method:"POST", body:JSON.stringify({})});
    toast(`Archived ${res.archived || 0} surfaced cards`);
    await loadCommand();
    return;
  }
  toast("No handler for cockpit action: " + action);
}
function pamaCardHTML(c){
  const why = meaningfulWhy(c.why_it_matters || "");
  const action = meaningfulActionText(c.recommended_action || "");
  const firstStep = meaningfulStepText(c.first_step || "");
  const track = meaningfulMetricText(c.tracking_metric || "");
  return `<div class="item action-card">
    <h3>${esc(c.title || c.signal || c.entry_id)}</h3>
    <div class="meta"><span class="tag">${esc(c.domain || "")}</span><span class="tag">${esc(c.tier || "")}</span><span class="tag">score ${esc(c.score)}</span></div>
    <div class="kv"><b>Source</b><span>${esc(c.source || "")}</span></div>
    ${kvHTML("Why", why)}
    ${kvHTML("Action", action)}
    ${kvHTML("First Step", firstStep)}
    ${kvHTML("Track", track)}
    <div class="buttons">
      <button class="ghost small danger-btn" onclick="dismissSignal('${esc(c.entry_id)}')">Dismiss</button>
      <button class="primary small" onclick="actOnSignal('${esc(c.entry_id)}','${esc(c.recommended_action||c.title||'')}')">Done — Log Result</button>
      <button class="ghost small" onclick="recontextualizeSignal('${esc(c.entry_id)}')">Re-translate</button>
    </div>
  </div>`;
}
function versionHTML(v){
  return `<div class="item">
    <h3>${esc(v.version)} — ${esc(v.name)}</h3>
    <p class="muted">${(v.features || []).map(esc).join(" • ")}</p>
  </div>`;
}
function changelogEntryHTML(v, currentVersion){
  const isCurrent = v.version === currentVersion;
  const features = (v.features || []).map(f=>`<li>${esc(f)}</li>`).join("");
  return `<div class="cl-entry${isCurrent ? " cl-current" : ""}">
    <div class="cl-head">
      <span class="cl-badge${isCurrent ? " cl-badge-current" : ""}">${esc(v.version)}</span>
      <span class="cl-name">${esc(v.name)}</span>
      ${isCurrent ? `<span class="pill good cl-pill">current</span>` : ""}
    </div>
    <ul class="cl-features">${features}</ul>
  </div>`;
}
async function loadChangelog(){
  const res = await api("/versions");
  const versions = (res.versions || []).slice().reverse();
  const current = res.current || "";
  const totalFeatures = versions.reduce((n,v)=>n+(v.features||[]).length, 0);
  $("changelogMeta").textContent = `${versions.length} versions · ${totalFeatures} shipped features · ${esc(current)}`;
  $("changelogList").innerHTML = versions.map(v=>changelogEntryHTML(v, current)).join("");
}

async function codify(){
  const base = collectBase();
  if(!base.raw_input){ toast("Paste raw input first"); return; }
  const btn = $("codifyBtn");
  const originalText = btn.textContent;
  btn.textContent = "Translating…";
  btn.disabled = true;
  try {
    const res = await api("/translate/ai", {method:"POST", body:JSON.stringify(base)});
    fillDraft(res.draft);
    toast(res.ai_used ? "AI signal translation complete" : "Signal translated (regex fallback)");
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
}
async function loopAnalyze(){
  const base = collectBase();
  if(!base.raw_input){ toast("Paste raw input first"); return; }
  const res = await api("/loop/analyze", {method:"POST", body:JSON.stringify(base)});
  const d = res.database_json;
  d.qa_scores = res.qa_scores;
  fillDraft(d);
  const scores = Object.entries(res.qa_scores || {}).map(([k,v])=>`<span class="tag">${esc(k)} ${esc(v)}</span>`).join("");
  const trace = (res.loop_trace || []).map(x=>`<div class="kv"><b>Loop ${esc(x.loop)}</b><span>${esc(x.plan)}</span></div>`).join("");
  $("saveOutput").innerHTML = `<div class="item"><h3>${esc(res.outcome)}</h3><div class="meta">${scores}</div>${trace}</div>`;
  toast("Loop analysis complete");
}
async function save(){
  let payload = collectDraft();
  if(!payload.raw_input){ toast("Paste raw input first"); return; }
  // If no signal or interpretation, queue for Claude — skip regex auto-fill
  const toQueue = !payload.signal && !payload.interpretation;
  if(toQueue) payload.status = "pending_claude";
  const res = await api("/entries", {method:"POST", body:JSON.stringify(payload)});
  const cards = res.context_packet?.cards || [];
  if(res.entry?.status === "pending_claude"){
    $("saveOutput").innerHTML = `<div class="item"><h3>Queued: ${esc(res.entry_id)}</h3><p class="muted">Saved to memory and added to the Claude processing queue. Ask Claude to run the queue to enrich this entry.</p></div>`;
    toast("Saved — queued for Claude");
  } else if(res.entry?.status === "needs_enrichment"){
    $("saveOutput").innerHTML = `<div class="item"><h3>Needs Enrichment: ${esc(res.entry_id)}</h3><p class="muted">Saved to memory, but the signal is still too generic or incomplete to trust as fully codified. Ask Claude to enrich it before relying on it in the cockpit.</p></div>`;
    toast("Saved — needs enrichment");
  } else {
    $("saveOutput").innerHTML = `<div class="item"><h3>Saved: ${esc(res.entry_id)}</h3><p class="muted">Created ${res.pull_rules?.length || 0} pull rules. Returned ${cards.length} surfaced memory cards.</p></div>` + cards.map(cardHTML).join("");
    toast("Saved to memory");
  }
  loadCommand();
  updateQueueBadge();
}
async function pullMemory(){
  const raw = $("pullInput").value.trim();
  if(!raw){ toast("Enter a pull query"); return; }
  const res = await api("/pull", {method:"POST", body:JSON.stringify({query: raw, domain: $("pullDomain").value})});
  const quick = res.quick_actions || [];
  const big = res.big_picture_actions || [];
  if(res.no_match){
    const opts = (res.no_match.suggested_options || []).map(o => `<li>${esc(o)}</li>`).join("");
    $("quickActionsList").innerHTML = `<div class="item"><h3>No actionable memory</h3><p class="muted">${esc(res.no_match.message)}</p><ul>${opts}</ul></div>`;
    $("bigActionsList").innerHTML = `<div class="item"><h3>Quiet cockpit</h3><p class="muted">No strong translated signal crossed the Pull threshold for "${esc(raw)}".</p></div>`;
    toast("No actionable memory matched");
    return;
  }
  $("quickActionsList").innerHTML = quick.length ? quick.map(pamaCardHTML).join("") : `<div class="item"><h3>No quick actions</h3><p class="muted">No immediate action matched this query.</p></div>`;
  $("bigActionsList").innerHTML = big.length ? big.map(pamaCardHTML).join("") : `<div class="item"><h3>No big-picture actions</h3><p class="muted">No macro pattern matched this query.</p></div>`;
  toast(`Pulled ${quick.length + big.length} action signals`);
}

function stockMetricHTML(label, item){
  if(!item) return `<div class="stat"><strong>n/a</strong><span class="muted">${esc(label)}</span></div>`;
  return `<div class="stat"><strong>${esc(item.display || item.value || "n/a")}</strong><span class="muted">${esc(label)}${item.end ? " · " + esc(item.end) : ""}</span></div>`;
}
function stockAnalysisHTML(res){
  const a = res.analysis || {};
  const company = a.company || {};
  const quote = a.quote || {};
  const financials = a.financials || {};
  const q = financials.latest_quarter || {};
  const y = financials.latest_annual || {};
  const decision = a.decision_frame || {};
  const signals = a.signals || [];
  const news = a.news || [];
  const memory = a.memory_context || [];
  const errors = a.errors || [];
  const signalHTML = signals.length ? signals.map(s=>`<div class="item">
    <h3>${esc(s.type || "signal")}: ${esc(s.direction || "watch")}</h3>
    <p class="muted">${esc(s.signal || "")}</p>
    <div class="kv"><b>Track</b><span>${esc(s.track || "")}</span></div>
  </div>`).join("") : `<div class="item"><h3>No signals</h3><p class="muted">Source data did not return enough signal yet.</p></div>`;
  const newsHTML = news.length ? news.slice(0,6).map(n=>`<div class="item">
    <h3>${esc(n.title || "Headline")}</h3>
    <p class="muted">${esc(n.published || "")}</p>
    ${n.link ? `<a href="${esc(n.link)}" target="_blank" rel="noopener">Open source</a>` : ""}
  </div>`).join("") : `<div class="item"><h3>No fresh headlines</h3><p class="muted">News source did not return headlines.</p></div>`;
  const memoryHTML = memory.length ? memory.slice(0,6).map(m=>`<div class="item">
    <h3>${esc(m.title || m.id)}</h3>
    <div class="meta"><span class="tag">${esc(m.domain || "")}</span><span class="tag">${esc(m.updated_at || "")}</span></div>
    <p class="muted">${esc(m.signal || m.interpretation || "")}</p>
  </div>`).join("") : `<div class="item"><h3>No local memory</h3><p class="muted">No prior ledger entries matched this company.</p></div>`;
  return `
    <div class="card">
      <div class="card-head">
        <div><p class="eyebrow">Decision Frame</p><h2>${esc(company.symbol || "")} · ${esc(company.name || "")}</h2></div>
        <span class="pill">${esc(decision.action || "watch")}</span>
      </div>
      <div class="stats">
        <div class="stat"><strong>${quote.price ? esc(fmtMoney(quote.price)) : "n/a"}</strong><span class="muted">Price</span></div>
        <div class="stat"><strong>${quote.one_year_return !== undefined && quote.one_year_return !== null ? esc(fmtPct(quote.one_year_return * 100)) : "n/a"}</strong><span class="muted">1Y move</span></div>
        ${stockMetricHTML("Last quarter revenue", q.revenue)}
        ${stockMetricHTML("Latest annual revenue", y.revenue)}
      </div>
      <div class="kv"><b>Reason</b><span>${esc(decision.reason || "")}</span></div>
      <div class="kv"><b>Next Step</b><span>${esc(decision.next_step || "")}</span></div>
      <div class="kv"><b>Track</b><span>${esc(decision.tracking_metric || "")}</span></div>
      ${errors.length ? `<div class="kv"><b>Source Errors</b><span>${esc(errors.join(" | "))}</span></div>` : ""}
    </div>
    <div class="grid two">
      <div class="card"><div class="card-head"><div><p class="eyebrow">Extracted Signals</p><h2>Pattern Read</h2></div></div><div class="list">${signalHTML}</div></div>
      <div class="card"><div class="card-head"><div><p class="eyebrow">Memory Context</p><h2>Prior Ledger</h2></div></div><div class="list">${memoryHTML}</div></div>
    </div>
    <div class="card"><div class="card-head"><div><p class="eyebrow">Current Headlines</p><h2>News Layer</h2></div></div><div class="list">${newsHTML}</div></div>
  `;
}
function loadStockIntel(){
  if(!$("stockOutput").innerHTML.trim()){
    $("stockOutput").innerHTML = `<div class="item"><h3>Ready</h3><p class="muted">Enter a ticker to generate a stock intelligence card from live market data, filings, news, and local memory.</p></div>`;
  }
}
async function analyzeStock(){
  const symbol = $("stockSymbolInput").value.trim();
  if(!symbol){ toast("Enter a ticker"); return; }
  const btn = $("analyzeStockBtn");
  const original = btn.textContent;
  btn.textContent = "Analyzing...";
  btn.disabled = true;
  $("saveStockIntel").disabled = true;
  try {
    const res = await api("/stock/analyze", {method:"POST", body:JSON.stringify({symbol, company:$("stockCompanyInput").value.trim()})});
    lastStockIntel = res;
    $("stockOutput").innerHTML = stockAnalysisHTML(res);
    $("saveStockIntel").disabled = false;
    toast("Stock intel generated");
  } catch(err) {
    $("stockOutput").innerHTML = `<div class="item"><h3>Stock analysis failed</h3><p class="muted">${esc(err.message)}</p></div>`;
    toast("Error: " + err.message);
  } finally {
    btn.textContent = original;
    btn.disabled = false;
  }
}
async function saveStockIntel(){
  const symbol = $("stockSymbolInput").value.trim();
  if(!symbol){ toast("Enter a ticker"); return; }
  const res = await api("/stock/analyze", {method:"POST", body:JSON.stringify({symbol, company:$("stockCompanyInput").value.trim(), save:true})});
  lastStockIntel = res;
  $("stockOutput").innerHTML = stockAnalysisHTML(res) + `<div class="item"><h3>Saved to memory</h3><p class="muted">${esc(res.entry_id || "")}</p></div>`;
  $("saveStockIntel").disabled = true;
  updateQueueBadge();
  toast("Stock intel saved");
}
async function dismissSignal(entryId){
  const reason = prompt("Why dismiss this signal?");
  if(!reason) return;
  await api(`/entries/${entryId}`, {method:"PATCH", body:JSON.stringify({action_status:"cancelled", status:"archived", result:`Dismissed from Command Pull: ${reason}`})});
  toast("Signal dismissed");
  pullMemory(); loadCommand();
}
async function actOnSignal(entryId, actionTitle){
  if(!confirm(`Do the action first — then come back here to log what happened.\n\n${actionTitle ? 'Action: ' + actionTitle + '\n\n' : ''}Ready to log a result?`)) return;
  const result = prompt("What result or proof did this produce?");
  if(!result) return;
  await api(`/entries/${entryId}`, {method:"PATCH", body:JSON.stringify({action_status:"done", result, status:"validated"})});
  toast("Result logged — signal validated");
  pullMemory(); loadCommand();
}
async function recontextualizeSignal(entryId){
  const instruction = prompt("How should the Translation Layer recontextualize this signal?");
  if(!instruction) return;
  await api(`/entries/${entryId}/recategorize`, {method:"POST", body:JSON.stringify({instruction})});
  toast("Signal recontextualized");
  pullMemory(); loadCommand();
}
async function loadMemory(){
  const q = encodeURIComponent($("searchInput").value.trim());
  const d = encodeURIComponent($("filterDomain").value);
  const res = await api(`/entries?q=${q}&domain=${d}&limit=100`);
  $("memoryList").innerHTML = res.entries.length ? res.entries.map(entryHTML).join("") : `<div class="item"><h3>No entries yet</h3><p class="muted">Go to <strong>New Entry</strong>, paste anything, and click <strong>Save Entry</strong>. Every signal you save appears here as a searchable, trackable record.</p></div>`;
}
async function loadActions(){
  const res = await api("/actions?status=open&limit=100");
  $("actionsList").innerHTML = res.actions.length ? res.actions.map(actionHTML).join("") : `<div class="item"><h3>No open actions</h3><p class="muted">Returned actions appear here after you save trackable signals.</p></div>`;
}
async function markDone(id){
  const result = prompt("Result / proof from this action?") || "done";
  await api(`/actions/${id}`, {method:"PATCH", body:JSON.stringify({status:"done", result})});
  toast("Action marked done");
  loadActions(); loadCommand();
}
async function extractPatternFromAction(actionId, entryId){
  const instruction = prompt("What pattern or new use should this action be recategorized into?");
  if(!instruction) return;
  if(entryId){
    await api(`/entries/${entryId}/recategorize`, {method:"POST", body:JSON.stringify({instruction:`Extract this returned action into a reusable pattern: ${instruction}`, tags:["pattern","extracted-action"]})});
  }
  await api(`/actions/${actionId}`, {method:"PATCH", body:JSON.stringify({status:"waiting", lesson_update:`Pattern extracted: ${instruction}`})});
  toast("Pattern extracted");
  loadActions(); loadCommand();
}
async function abortAction(id){
  const reason = prompt("Why abort this action?");
  if(!reason) return;
  await api(`/actions/${id}`, {method:"PATCH", body:JSON.stringify({status:"cancelled", result:`Aborted: ${reason}`})});
  toast("Action aborted");
  loadActions(); loadCommand();
}
async function recategorizeEntry(id){
  const instruction = prompt("What new use should this dormant info have?");
  if(!instruction) return;
  await api(`/entries/${id}/recategorize`, {method:"POST", body:JSON.stringify({instruction})});
  toast("Info recategorized");
  loadDormant(); loadCommand(); loadMemory();
}
async function deleteEntry(id){
  const ok = confirm("Permanently delete this entry from the database? This cannot be undone.");
  if(!ok) return;
  await api(`/entries/${id}`, {method:"DELETE"});
  toast("Entry permanently deleted");
  loadDormant(); loadCommand(); loadMemory();
}
async function loadCommand(){
  const d = await api("/command");
  if(d.claude_queue !== undefined) updateQueueBadge(d.claude_queue);
  const domainCounts = countMap(d.domains);
  const actionCounts = countMap(d.domain_action_load, "open_actions");
  $("commandStats").innerHTML = [
    ["Value records", d.total_entries],
    ["Need routing", d.claude_queue],
    ["Active routes", d.open_actions],
    ["Closed loops", d.completed_actions],
    ["Close rate", `${d.completion_rate}%`],
    ["Intelligence cards", d.surfaced_open],
    ["Contextualized", d.contextualized_entries || 0],
    ["Context links", d.contextual_links || 0],
    ["Proof backlog", d.result_backlog],
    ["Validated", d.validated_or_upgraded],
    ["Translation gaps", d.weak_translation],
    ["Import batches", d.import_batches || 0],
    ["Imported rows", d.import_rows || 0],
    ["Watchlist items", d.imported_watchlists || 0],
  ].map(([k,v])=>`<div class="stat${k==='Need routing'&&v>0?' stat-queue':''}"><strong>${esc(v)}</strong><span class="muted">${esc(k)}</span></div>`).join("");
  renderInnbankArchitecture(d);
  renderInnbankQuestions();
  renderPlaneCards("innbankDataPlanes", DATA_PLANES, domainCounts, actionCounts);
  renderPlaneCards("innbankSubplanes", SUB_CONTROL_PLANES, domainCounts, actionCounts);
  renderImportPlanes(d.imports || {});
  const cockpit = d.cockpit || {};
  if(d.total_entries === 0){
    $("warningLane").innerHTML = `<div class="item callout advisory"><h3>Start routing reality</h3><p class="muted">Go to <strong>New Entry</strong>, capture a real signal, and start building the control plane one value record at a time.</p></div>`;
  } else {
    $("warningLane").innerHTML = (cockpit.warnings || []).length ? cockpit.warnings.map(calloutHTML).join("") : `<div class="item"><h3>Quiet</h3><p class="muted">No warning callouts.</p></div>`;
  }
  $("cautionLane").innerHTML = (cockpit.cautions || []).length ? cockpit.cautions.map(calloutHTML).join("") : `<div class="item"><h3>Quiet</h3><p class="muted">No caution callouts.</p></div>`;
  $("advisoryLane").innerHTML = (cockpit.advisories || []).map(calloutHTML).join("");
  $("cockpitChecklist").innerHTML = (cockpit.checklist || []).map(x=>`<div class="check"><span></span><p>${esc(x)}</p></div>`).join("") + `<div class="item"><h3>Go-around</h3><p class="muted">${esc(cockpit.go_around || "")}</p></div>`;
  loadVersions();
  if(!$("dormantList").innerHTML.trim()) {
    $("dormantList").innerHTML = `<div class="item"><h3>Detector ready</h3><p class="muted">Press Detect to find systems missing a metric, trigger, route, or result.</p></div>`;
  }
  if(!$("quickActionsList").innerHTML.trim()) {
    $("quickActionsList").innerHTML = `<div class="item"><h3>Ready</h3><p class="muted">Enter a routing query above to pull the highest-value immediate moves.</p></div>`;
  }
  if(!$("bigActionsList").innerHTML.trim()) {
    $("bigActionsList").innerHTML = `<div class="item"><h3>Ready</h3><p class="muted">System-level re-routing moves appear here.</p></div>`;
  }
}
async function rewireMemory(){
  const btn = $("rewireMemory");
  const originalText = btn.textContent;
  btn.textContent = "Rewiring…";
  btn.disabled = true;
  try {
    const res = await api("/context/rewire", {method:"POST", body:JSON.stringify({})});
    toast(`Rewired ${res.processed || 0} entries`);
    loadCommand(); loadMemory(); loadActions(); loadPatterns();
  } catch(err) {
    toast("Error: " + err.message);
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
}
async function loadDormant(){
  const d = await api("/command/dormant");
  const weak = d.weak_entries || [];
  const stale = d.stale_actions || [];
  const doneNoResult = d.done_without_result || [];
  const due = d.review_due || [];
  $("dormantList").innerHTML =
    `<div class="item"><h3>${esc(d.total_dormant_risks)} dormant risks found</h3><p class="muted">${esc(d.principle)}</p></div>` +
    (weak.length ? `<div class="item"><h3>Weak Signals</h3><p class="muted">These entries need stronger trackability.</p></div>${weak.map(dormantEntryHTML).join("")}` : "") +
    (stale.length ? `<div class="item"><h3>Stale Actions</h3><p class="muted">${stale.map(a=>esc(a.action_title)).join(" • ")}</p></div>` : "") +
    (doneNoResult.length ? `<div class="item"><h3>Done Without Proof</h3><p class="muted">${doneNoResult.map(a=>esc(a.action_title)).join(" • ")}</p></div>` : "") +
    (due.length ? `<div class="item"><h3>Review Due</h3><p class="muted">${due.map(e=>esc(e.title || e.id)).join(" • ")}</p></div>` : "");
}
async function loadVersions(){
  const res = await api("/versions");
  $("versionsList").innerHTML = (res.versions || []).map(versionHTML).join("");
}
async function loadPatterns(){
  const res = await api("/patterns");
  const insights = res.insights || [];
  const engine = res.engine || {};
  const engineCards = engine.cards || [];
  const engineHTML = engineCards.map(c=>{
    const action = meaningfulActionText(c.action || "");
    const firstStep = meaningfulStepText(c.first_step || "");
    const metric = meaningfulMetricText(c.tracking_metric || "");
    return `<div class="item pattern-engine-card ${esc(c.severity)}">
    <h3>${esc(c.name)}</h3>
    <div class="meta"><span class="tag">${esc(c.type)}</span><span class="tag">${esc(c.severity)}</span><span class="tag">score ${esc(c.score)}</span></div>
    <div class="kv"><b>Interpretation</b><span>${esc(c.interpretation)}</span></div>
    ${kvHTML("Action", action)}
    ${kvHTML("First Step", firstStep)}
    ${kvHTML("Metric", metric)}
    <div class="kv"><b>Trigger</b><span>${esc(c.resurfacing_trigger)}</span></div>
  </div>`;
  }).join("");
  const insightHTML = insights.map(i=>{
    const action = meaningfulActionText(i.action || "");
    const track = meaningfulMetricText(i.track || "");
    return `<div class="item insight-card">
    <h3>${esc(i.name)}</h3>
    <div class="meta"><span class="tag">${esc(i.type)}</span></div>
    <div class="kv"><b>Insight</b><span>${esc(i.why_it_matters)}</span></div>
    ${kvHTML("Action", action)}
    ${kvHTML("Track", track)}
  </div>`;
  }).join("");
  const patternHTML = res.patterns.length ? res.patterns.map(p=>`<div class="item"><h3>${esc(p.pattern)}</h3><div class="meta"><span class="tag">${esc(p.entry_count)} reps</span><span class="tag">${esc(p.confidence)}</span>${(p.domains||[]).map(d=>`<span class="tag">${esc(d)}</span>`).join("")}</div></div>`).join("") : `<div class="item"><h3>No patterns yet</h3><p class="muted">Patterns build as repeated lessons enter memory.</p></div>`;
  const summary = engine.summary || {};
  $("patternsList").innerHTML = `<div class="item"><h3>Cross-Database Insights</h3><p class="muted">Synthesized from repeated patterns, action backlog, risk clusters, domains, and signal mix.</p></div>${insightHTML}<div class="item"><h3>Pattern Engine Cards</h3><p class="muted">Scanned ${esc(summary.entries_scanned || 0)} entries and ${esc(summary.actions_scanned || 0)} actions. Warnings: ${esc(summary.warnings || 0)}. Cautions: ${esc(summary.cautions || 0)}.</p></div>${engineHTML}<div class="item"><h3>Pattern Records</h3><p class="muted">Underlying repeated lessons stored in the database.</p></div>${patternHTML}`;
}
async function runPatternEngine(){
  const res = await api("/pattern-engine/scan", {method:"POST", body:JSON.stringify({save:true, scan_type:"manual"})});
  toast(`Pattern scan saved: ${res.summary.cards} cards`);
  loadPatterns();
}

async function checkAiStatus(){
  try {
    const s = await api("/ai/status");
    const note = $("aiStatusNote");
    if(s.ai_enabled){
      note.className = "ai-status-note ai-status-on";
      note.innerHTML = `<span class="ai-dot on"></span>AI translation active &mdash; Claude Opus 4.8`;
    } else {
      note.className = "ai-status-note ai-status-off";
      const hint = s.hint || "Set ANTHROPIC_API_KEY before starting the server";
      note.innerHTML = `<span class="ai-dot off"></span>AI translation inactive &mdash; <code>${esc(hint)}</code>`;
    }
  } catch(e) { /* silent — don't break load if status check fails */ }
}

$("codifyBtn").addEventListener("click", codify);
$("loopBtn").addEventListener("click", loopAnalyze);
$("saveBtn").addEventListener("click", save);
$("pullBtn").addEventListener("click", pullMemory);
$("rewireMemory").addEventListener("click", rewireMemory);
$("refreshMemory").addEventListener("click", loadMemory);
$("refreshActions").addEventListener("click", loadActions);
$("refreshCommand").addEventListener("click", loadCommand);
$("dormantBtn").addEventListener("click", loadDormant);
$("refreshPatterns").addEventListener("click", loadPatterns);
$("scanPatterns").addEventListener("click", runPatternEngine);
$("refreshChangelog").addEventListener("click", loadChangelog);
$("refreshQueue").addEventListener("click", loadQueue);
$("analyzeStockBtn").addEventListener("click", analyzeStock);
$("saveStockIntel").addEventListener("click", saveStockIntel);
$("searchInput").addEventListener("input", ()=>{ clearTimeout(window.__searchTimer); window.__searchTimer=setTimeout(loadMemory,250); });
$("filterDomain").addEventListener("change", loadMemory);
$("clearBtn").addEventListener("click", ()=>{ document.querySelectorAll("textarea,input").forEach(el=>{ if(!["searchInput"].includes(el.id)) el.value=""; }); $("sourceTypeInput").value=""; $("draftPill").textContent="empty"; $("draftPill").className="pill muted"; $("saveOutput").innerHTML=""; });
$("exportBtn").addEventListener("click", ()=>{ window.location.href="/api/export"; });

loadCommand();
checkAiStatus();
updateQueueBadge();
