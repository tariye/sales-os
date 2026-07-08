const API = "/api";
const $ = id => document.getElementById(id);
const esc = v => String(v ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;");
const tagsFrom = s => String(s||"").split(/[#,]/).map(x=>x.trim().toLowerCase()).filter(Boolean).filter((x,i,a)=>a.indexOf(x)===i);
let lastDraft = null;

async function api(path, opts={}){
  const res = await fetch(API + path, { ...opts, headers:{"Content-Type":"application/json", ...(opts.headers||{})} });
  const txt = await res.text();
  const data = txt ? JSON.parse(txt) : {};
  if(!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
function toast(msg){ const t=$("toast"); t.textContent=msg; t.classList.remove("hidden"); setTimeout(()=>t.classList.add("hidden"),2500); }

function switchTab(tab){
  document.querySelectorAll(".tab").forEach(b=>b.classList.toggle("active", b.dataset.tab===tab));
  document.querySelectorAll(".panel").forEach(p=>p.classList.toggle("active", p.id===tab));
  if(tab==="command") loadCommand();
  if(tab==="queue") loadQueue();
  if(tab==="sales") loadSalesTrends();
  if(tab==="watchlist") loadWatchlist();
  if(tab==="memory") loadMemory();
  if(tab==="actions") loadActions();
  if(tab==="patterns") loadPatterns();
  if(tab==="changelog") loadChangelog();
}

document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>switchTab(b.dataset.tab)));

// ═══════════════════════════════════════════════════════════════
// DUMP TAB (Intelligence Input)
// ═══════════════════════════════════════════════════════════════

function collectBase(){
  return {
    raw_input: $("rawInput").value.trim(),
    domain: $("domainInput").value,
    entity: $("entityInput").value.trim(),
    tags: tagsFrom($("tagsInput").value),
    source_type: $("sourceTypeInput").value,
  };
}

function collectDraft(){
  const base = collectBase();
  return {...base,
    title: $("titleInput").value.trim(),
    signal: $("signalInput").value.trim(),
    interpretation: $("interpretationInput").value.trim(),
    signal_role: $("signalRoleInput").value,
    confidence: $("confidenceInput").value,
  };
}

async function save(){
  let payload = collectDraft();
  if(!payload.raw_input){ toast("Paste raw input first"); return; }
  const toQueue = !payload.signal && !payload.interpretation;
  if(toQueue) payload.status = "pending_claude";
  const res = await api("/entries", {method:"POST", body:JSON.stringify(payload)});
  const cards = res.context_packet?.cards || [];
  if(toQueue){
    $("saveOutput").innerHTML = `<div class="item"><h3>Queued: ${esc(res.entry_id)}</h3><p class="muted">Saved and added to Claude processing queue. Ask Claude Code to run the queue.</p></div>`;
    toast("Saved — queued for Claude");
  } else {
    $("saveOutput").innerHTML = `<div class="item"><h3>Saved: ${esc(res.entry_id)}</h3><p class="muted">Created ${res.pull_rules?.length || 0} pull rules. Returned ${cards.length} surfaced cards.</p></div>`;
    toast("Saved to memory");
  }
  loadCommand();
  updateQueueBadge();
}

async function codify(){
  const payload = collectBase();
  if(!payload.raw_input){ toast("Paste raw input first"); return; }
  $("codifyBtn").disabled = true;
  try {
    const res = await api("/codify", {method:"POST", body:JSON.stringify(payload)});
    const draft = res.draft || {};
    ["title","signal","interpretation","signal_role","confidence"].forEach(f=>{
      if(draft[f]) $(f + "Input").value = draft[f];
    });
    lastDraft = draft;
    $("draftPill").textContent = "ready";
    $("draftPill").className = "pill good";
    toast("Translated");
  } catch(e){ toast("Error: " + e.message); }
  finally{ $("codifyBtn").disabled = false; }
}

// ═══════════════════════════════════════════════════════════════
// QUEUE TAB
// ═══════════════════════════════════════════════════════════════

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
    ? `<div class="stat stat-queue"><strong>${esc(entries.length)}</strong><span class="muted">Total queued</span></div>${domainStats}`
    : `<p class="muted" style="margin:0">Queue is empty.</p>`;
  $("queueList").innerHTML = entries.length
    ? entries.map(e => `<div class="item item-queued"><h3>${esc(e.title || e.id)}</h3><p class="muted">${esc((e.raw_input||"").slice(0,200))}</p></div>`).join("")
    : `<div class="item"><h3>Queue is empty</h3><p class="muted">Save entries from the Dump tab — they land here automatically when no signal is pre-filled.</p></div>`;
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

// ═══════════════════════════════════════════════════════════════
// SALES TRENDS TAB
// ═══════════════════════════════════════════════════════════════

async function loadSalesTrends(){
  try {
    const res = await api("/sales/trends?days=30");
    const trends = res.trends || [];
    $("trendsList").innerHTML = trends.slice(0, 10).map(t =>
      `<div class="item"><div class="kv"><b>${esc(t.date)}</b><span>${esc(t.signal_count)} signals, avg metric: ${esc((t.avg_metric||0).toFixed(2))}</span></div></div>`
    ).join("");
    toast("Trends loaded");
  } catch(e){
    $("trendsList").innerHTML = `<div class="item"><p class="muted">Error: ${esc(e.message)}</p></div>`;
  }
}

// ═══════════════════════════════════════════════════════════════
// WATCHLIST TAB
// ═══════════════════════════════════════════════════════════════

async function loadWatchlist(){
  try {
    const res = await api("/sales/watchlist");
    const items = res.items || [];
    $("watchlistMeta").innerHTML = `<div class="stat stat-queue"><strong>${esc(items.length)}</strong><span class="muted">Tracked items</span></div>`;
    $("watchlistList").innerHTML = items.map(item => `
      <div class="item">
        <h3>${esc(item.item)}</h3>
        <div class="meta"><span class="tag">${esc(item.status)}</span></div>
        <div class="kv"><b>Price</b><span>$${esc(item.price.toFixed(2))}</span></div>
        <div class="kv"><b>Cost</b><span>$${esc(item.cost.toFixed(2))}</span></div>
        <div class="kv"><b>Margin</b><span style="color:var(--accent2)">$${esc(item.margin.toFixed(2))}</span></div>
        <div class="kv"><b>Signal</b><span>${esc(item.signal)}</span></div>
      </div>
    `).join("");
    toast("Watchlist loaded");
  } catch(e){
    $("watchlistList").innerHTML = `<div class="item"><p class="muted">Error: ${esc(e.message)}</p></div>`;
  }
}

// ═══════════════════════════════════════════════════════════════
// COMMAND CENTER TAB (Existing)
// ═══════════════════════════════════════════════════════════════

async function loadCommand(){
  try {
    const d = await api("/command");
    $("commandStats").innerHTML = [
      ["Total entries", d.total_entries],
      ["Queued", d.claude_queue],
      ["Open actions", d.open_actions],
      ["Patterns", d.patterns],
    ].map(([k,v])=>`<div class="stat${k==='Queued'&&v>0?' stat-queue':''}"><strong>${esc(v)}</strong><span class="muted">${esc(k)}</span></div>`).join("");
    const cockpit = d.cockpit || {};
    $("warningLane").innerHTML = (cockpit.warnings || []).length
      ? (cockpit.warnings || []).map(w => `<div class="item"><h3>${esc(w.title)}</h3><p class="muted">${esc(w.message)}</p></div>`).join("")
      : `<div class="item"><p class="muted">No warnings.</p></div>`;
    $("cautionLane").innerHTML = (cockpit.cautions || []).length
      ? (cockpit.cautions || []).map(c => `<div class="item"><h3>${esc(c.title)}</h3><p class="muted">${esc(c.message)}</p></div>`).join("")
      : `<div class="item"><p class="muted">No cautions.</p></div>`;
    $("advisoryLane").innerHTML = (cockpit.advisories || []).map(a => `<div class="item"><h3>${esc(a.title)}</h3><p class="muted">${esc(a.message)}</p></div>`).join("");
  } catch(e){ toast("Error: " + e.message); }
}

// ═══════════════════════════════════════════════════════════════
// MEMORY DB TAB (Existing)
// ═══════════════════════════════════════════════════════════════

async function loadMemory(){
  const q = $("searchInput").value.trim();
  const domain = $("filterDomain").value;
  try {
    const res = await api(`/entries?q=${encodeURIComponent(q)}&domain=${encodeURIComponent(domain)}`);
    const entries = res.entries || [];
    $("memoryList").innerHTML = entries.length
      ? entries.slice(0,50).map(e => `
        <div class="item">
          <h3>${esc(e.title || e.id)}</h3>
          <div class="meta"><span class="tag">${esc(e.domain)}</span><span class="tag">${esc(e.signal_role)}</span></div>
          <p class="muted">${esc((e.interpretation || e.signal || "").slice(0,120))}</p>
        </div>
      `).join("")
      : `<div class="item"><p class="muted">No entries found.</p></div>`;
  } catch(e){ toast("Error: " + e.message); }
}

// ═══════════════════════════════════════════════════════════════
// ACTIONS TAB (Existing)
// ═══════════════════════════════════════════════════════════════

async function loadActions(){
  try {
    const res = await api("/actions");
    const actions = res.actions || [];
    $("actionsList").innerHTML = actions.length
      ? actions.slice(0, 50).map(a => `
        <div class="item">
          <h3>${esc(a.title)}</h3>
          <div class="meta"><span class="tag">${esc(a.status)}</span></div>
          <div class="kv"><b>From</b><span>${esc(a.entry_id)}</span></div>
        </div>
      `).join("")
      : `<div class="item"><p class="muted">No open actions.</p></div>`;
  } catch(e){ toast("Error: " + e.message); }
}

// ═══════════════════════════════════════════════════════════════
// PATTERNS TAB (Existing)
// ═══════════════════════════════════════════════════════════════

async function loadPatterns(){
  try {
    const res = await api("/patterns");
    const patterns = res.patterns || [];
    $("patternsList").innerHTML = patterns.length
      ? patterns.map(p => `<div class="item"><h3>${esc(p.pattern)}</h3><div class="meta"><span class="tag">${esc(p.entry_count || 0)} reps</span></div></div>`).join("")
      : `<div class="item"><p class="muted">No patterns yet.</p></div>`;
  } catch(e){ toast("Error: " + e.message); }
}

// ═══════════════════════════════════════════════════════════════
// CHANGELOG TAB (Existing)
// ═══════════════════════════════════════════════════════════════

async function loadChangelog(){
  try {
    const res = await api("/versions");
    const versions = res.versions || [];
    const current = res.current || "";
    const meta = versions.length ? `${versions.length} versions • ${versions.map(v=>v.features?.length || 0).reduce((a,b)=>a+b, 0)} features total` : "";
    $("changelogMeta").textContent = meta;
    $("changelogList").innerHTML = versions.reverse().map(v => `
      <div class="cl-entry${v.version === current ? ' cl-current' : ''}">
        <div class="cl-head">
          <div><h3 class="cl-name">${esc(v.version)}</h3><p class="muted">${esc(v.name)}</p></div>
          ${v.version === current ? '<span class="cl-badge cl-badge-current">current</span>' : ''}
        </div>
        <ul class="cl-features">${(v.features || []).map(f => `<li>${esc(f)}</li>`).join("")}</ul>
      </div>
    `).join("");
  } catch(e){ toast("Error: " + e.message); }
}

// ═══════════════════════════════════════════════════════════════
// PULL ACTIONABLE MEMORY (PAM-A)
// ═══════════════════════════════════════════════════════════════

async function pullMemory(){
  const q = $("pullInput").value.trim();
  const domain = $("pullDomain").value;
  if(!q){ toast("Enter a search term"); return; }
  try {
    const res = await api(`/pull?q=${encodeURIComponent(q)}&domain=${encodeURIComponent(domain)}`, {method:"POST", body:JSON.stringify({})});
    toast("Memory pulled");
    switchTab("command");
  } catch(e){ toast("Error: " + e.message); }
}

// ═══════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════

if($("saveBtn")) $("saveBtn").addEventListener("click", save);
if($("codifyBtn")) $("codifyBtn").addEventListener("click", codify);
if($("clearBtn")) $("clearBtn").addEventListener("click", ()=>{
  ["rawInput","titleInput","signalInput","interpretationInput","entityInput","tagsInput"].forEach(id=>{
    if($(id)) $(id).value="";
  });
  const p = $("draftPill");
  if(p) {
    p.textContent="empty";
    p.className="pill muted";
  }
});
if($("refreshQueue")) $("refreshQueue").addEventListener("click", loadQueue);
if($("refreshTrends")) $("refreshTrends").addEventListener("click", loadSalesTrends);
if($("refreshWatchlist")) $("refreshWatchlist").addEventListener("click", loadWatchlist);
if($("refreshCommand")) $("refreshCommand").addEventListener("click", loadCommand);
if($("refreshMemory")) $("refreshMemory").addEventListener("click", loadMemory);
if($("refreshActions")) $("refreshActions").addEventListener("click", loadActions);
if($("refreshPatterns")) $("refreshPatterns").addEventListener("click", loadPatterns);
if($("refreshChangelog")) $("refreshChangelog").addEventListener("click", loadChangelog);
if($("pullBtn")) $("pullBtn").addEventListener("click", pullMemory);
if($("searchInput")) $("searchInput").addEventListener("input", () => { clearTimeout(window.__searchTimer); window.__searchTimer=setTimeout(loadMemory,250); });
if($("filterDomain")) $("filterDomain").addEventListener("change", loadMemory);
if($("exportBtn")) $("exportBtn").addEventListener("click", ()=>{ window.location.href="/api/export"; });

// Initial load on page startup
async function initializeApp(){
  try {
    await Promise.all([
      loadCommand(),
      loadQueue(),
      loadWatchlist(),
      loadChangelog()
    ]);
  } catch(e){
    console.error("Init error:", e);
  }
  checkAiStatus();
  updateQueueBadge();
}

async function checkAiStatus(){
  try {
    const s = await api("/ai/status");
    const note = $("aiStatusNote");
    if(!note) return;
    if(s.ai_enabled){
      note.className = "ai-status-note ai-status-on";
      note.innerHTML = `<span class="ai-dot on"></span>AI active — Claude Opus 4.8`;
    } else {
      note.className = "ai-status-note ai-status-off";
      note.innerHTML = `<span class="ai-dot off"></span>AI inactive — Set ANTHROPIC_API_KEY`;
    }
  } catch(e) {}
}

initializeApp();
