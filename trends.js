const LEDGER_STORAGE_KEY = "sales-os-demand-ledger";
const SNAPSHOT_STORAGE_KEY = "sales-os-snapshot-history";

const defaultSeedSnapshots = [
  {
    capturedAt: "2026-06-27T18:00:00.000Z",
    items: [
      { id: "imac-2011", item: "iMac 21.5 2011", category: "Computers", route: "FB Local", salesVolume: 18, sellThrough: 3.3 },
      { id: "macbook-pro-2012", item: "2012 MacBook Pro 13", category: "Computers", route: "Both", salesVolume: 231, sellThrough: 14.4 },
      { id: "altima-door-handle", item: "Nissan Altima Driver Door Handle", category: "Auto Parts", route: "eBay", salesVolume: 40, sellThrough: 12.8 },
      { id: "altima-cluster", item: "Nissan Altima Instrument Cluster", category: "Auto Parts", route: "eBay", salesVolume: 49, sellThrough: 16.2 },
      { id: "raspberry-pi-4-4gb", item: "Raspberry Pi 4 Model B 4GB", category: "Compute Boards", route: "eBay", salesVolume: 5, sellThrough: 30.1 },
      { id: "raspberry-pi-5-8gb", item: "Raspberry Pi 5 8GB", category: "Compute Boards", route: "eBay", salesVolume: 7, sellThrough: 18.6 },
      { id: "jetson-nano", item: "NVIDIA Jetson Nano Developer Kit", category: "Compute Boards", route: "eBay", salesVolume: 10, sellThrough: 20.4 },
      { id: "beaglebone-black", item: "BeagleBone Black", category: "Compute Boards", route: "eBay", salesVolume: 21, sellThrough: 27.2 }
    ]
  },
  {
    capturedAt: "2026-06-30T18:00:00.000Z",
    items: [
      { id: "imac-2011", item: "iMac 21.5 2011", category: "Computers", route: "FB Local", salesVolume: 21, sellThrough: 3.8 },
      { id: "macbook-pro-2012", item: "2012 MacBook Pro 13", category: "Computers", route: "Both", salesVolume: 248, sellThrough: 15.6 },
      { id: "altima-door-handle", item: "Nissan Altima Driver Door Handle", category: "Auto Parts", route: "eBay", salesVolume: 47, sellThrough: 13.6 },
      { id: "altima-cluster", item: "Nissan Altima Instrument Cluster", category: "Auto Parts", route: "eBay", salesVolume: 54, sellThrough: 17.4 },
      { id: "raspberry-pi-4-4gb", item: "Raspberry Pi 4 Model B 4GB", category: "Compute Boards", route: "eBay", salesVolume: 6, sellThrough: 36.8 },
      { id: "raspberry-pi-5-8gb", item: "Raspberry Pi 5 8GB", category: "Compute Boards", route: "eBay", salesVolume: 9, sellThrough: 22.7 },
      { id: "jetson-nano", item: "NVIDIA Jetson Nano Developer Kit", category: "Compute Boards", route: "eBay", salesVolume: 13, sellThrough: 23.5 },
      { id: "beaglebone-black", item: "BeagleBone Black", category: "Compute Boards", route: "eBay", salesVolume: 24, sellThrough: 31.1 }
    ]
  }
];

let liveLedgerRows = [];
let liveDiscoveryProducts = [];
let liveDiscoverySnapshots = [];
let seedSnapshots = defaultSeedSnapshots;

const trendFilter = document.querySelector("#trendFilter");
const trendSearchInput = document.querySelector("#trendSearchInput");
const trendTableBody = document.querySelector("#trendTableBody");
const topMoversList = document.querySelector("#topMoversList");
const runFreshPullButton = document.querySelector("#runFreshPullButton");
const refreshDataButton = document.querySelector("#refreshDataButton");
const showHighVolumeButton = document.querySelector("#showHighVolumeButton");
const captureSnapshotButton = document.querySelector("#captureSnapshotButton");
const resetSnapshotsButton = document.querySelector("#resetSnapshotsButton");
const trendActionState = document.querySelector("#trendActionState");
const discoveryPanel = document.querySelector("#discoveryPanel");
const discoveryResultsList = document.querySelector("#discoveryResultsList");

const summaryTargets = {
  trendingUp: document.querySelector("#trendingUpValue"),
  fastestMover: document.querySelector("#fastestMoverValue"),
  largestGain: document.querySelector("#largestGainValue"),
  avgMomentum: document.querySelector("#avgMomentumValue"),
  lastSnapshot: document.querySelector("#lastSnapshotValue")
};

refreshLiveBindings();
let snapshots = loadSnapshots();
let highVolumeMode = true;
let trendActionMessage = "";

function currentLiveData() {
  if (!window.SALES_OS_LIVE_DATA || typeof window.SALES_OS_LIVE_DATA !== "object") {
    return null;
  }

  return window.SALES_OS_LIVE_DATA;
}

function currentGeneratedAt() {
  return currentLiveData()?.generatedAt || "";
}

function supportsFreshPull() {
  return window.location.protocol === "http:" || window.location.protocol === "https:";
}

function refreshLiveBindings() {
  const liveData = currentLiveData();
  liveLedgerRows =
    liveData && Array.isArray(liveData.ledgerRows)
      ? liveData.ledgerRows
      : [];
  liveDiscoveryProducts =
    liveData && Array.isArray(liveData.discoveryProducts)
      ? liveData.discoveryProducts
      : [];
  liveDiscoverySnapshots =
    liveData && Array.isArray(liveData.discoverySnapshots)
      ? liveData.discoverySnapshots
      : [];
  seedSnapshots =
    liveData && Array.isArray(liveData.snapshots) && liveData.snapshots.length
      ? liveData.snapshots
      : defaultSeedSnapshots;
}

function loadLatestLiveDataScript() {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `./data/live-data.js?ts=${Date.now()}`;
    script.async = true;
    script.dataset.liveReload = "true";
    script.onload = () => {
      script.remove();
      resolve();
    };
    script.onerror = () => {
      script.remove();
      reject(new Error("Unable to load the latest live data file."));
    };
    document.head.append(script);
  });
}

function setRefreshButtonsDisabled(disabled) {
  if (runFreshPullButton) {
    runFreshPullButton.disabled = disabled || !supportsFreshPull();
  }

  if (refreshDataButton) {
    refreshDataButton.disabled = disabled;
  }
}

function loadSnapshots() {
  const stored = window.localStorage.getItem(SNAPSHOT_STORAGE_KEY);
  if (!stored) {
    return cloneSeedSnapshots();
  }

  try {
    const parsed = JSON.parse(stored);
    return mergeSnapshots(seedSnapshots, parsed);
  } catch (_error) {
    return cloneSeedSnapshots();
  }
}

function cloneSeedSnapshots() {
  return JSON.parse(JSON.stringify(seedSnapshots));
}

function mergeSnapshots(baseSnapshots, storedSnapshots) {
  const merged = [...baseSnapshots, ...(Array.isArray(storedSnapshots) ? storedSnapshots : [])];
  const deduped = new Map();
  merged.forEach((snapshot) => {
    deduped.set(snapshot.capturedAt, snapshot);
  });
  return Array.from(deduped.values()).sort((left, right) =>
    left.capturedAt.localeCompare(right.capturedAt)
  );
}

function persistSnapshots() {
  window.localStorage.setItem(SNAPSHOT_STORAGE_KEY, JSON.stringify(snapshots));
}

function asNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDelta(value) {
  const rounded = asNumber(value).toFixed(0);
  return value > 0 ? `+${rounded}` : rounded;
}

function formatPercentChange(value) {
  const rounded = asNumber(value).toFixed(1);
  return value > 0 ? `+${rounded}%` : `${rounded}%`;
}

function formatPlainPercent(value) {
  return `${asNumber(value).toFixed(2)}%`;
}

function formatDateTime(value) {
  if (!value) {
    return "None";
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
}

function currentLedgerRows() {
  const stored = window.localStorage.getItem(LEDGER_STORAGE_KEY);
  if (!stored) {
    return liveLedgerRows;
  }

  try {
    const parsed = JSON.parse(stored);
    const byId = new Map(liveLedgerRows.map((row) => [row.id, row]));
    const customRows = [];

    parsed.forEach((row) => {
      if (!byId.has(row.id)) {
        customRows.push(row);
        return;
      }

      const liveRow = byId.get(row.id);
      byId.set(row.id, {
        ...liveRow,
        route: row.route || liveRow.route,
        buyingPrice: hasValue(row.buyingPrice) ? asNumber(row.buyingPrice) : liveRow.buyingPrice,
        fees: hasValue(row.fees) ? asNumber(row.fees) : liveRow.fees,
        shipping: hasValue(row.shipping) ? asNumber(row.shipping) : liveRow.shipping,
        supplies: hasValue(row.supplies) ? asNumber(row.supplies) : liveRow.supplies,
        buyEvidenceUrl: row.buyEvidenceUrl || liveRow.buyEvidenceUrl,
        buyerSalesTax: hasValue(row.buyerSalesTax) ? asNumber(row.buyerSalesTax) : asNumber(liveRow.buyerSalesTax),
        buyerTotalPaid: hasValue(row.buyerTotalPaid) ? asNumber(row.buyerTotalPaid) : asNumber(liveRow.buyerTotalPaid),
        transactionFeeRate: hasValue(row.transactionFeeRate) ? asNumber(row.transactionFeeRate) : asNumber(liveRow.transactionFeeRate),
        buyerPersona: row.buyerPersona || liveRow.buyerPersona,
        buyerProblem: row.buyerProblem || liveRow.buyerProblem,
        desiredOutcome: row.desiredOutcome || liveRow.desiredOutcome,
        buyerFriction: row.buyerFriction || liveRow.buyerFriction,
        honestUseCase: row.honestUseCase || liveRow.honestUseCase,
        nextAction: row.nextAction || liveRow.nextAction,
        outcomeStatus: row.outcomeStatus || liveRow.outcomeStatus,
        decisionStatus: row.decisionStatus || liveRow.decisionStatus,
        exceptionReason: row.exceptionReason || liveRow.exceptionReason,
        desiredProfit: hasValue(row.desiredProfit) ? asNumber(row.desiredProfit) : asNumber(liveRow.desiredProfit),
        notes: row.notes || liveRow.notes
      });
    });

    return [...byId.values(), ...customRows];
  } catch (_error) {
    return liveLedgerRows;
  }
}

function hasValue(value) {
  return value !== undefined && value !== null && value !== "";
}

function currentTrackedList() {
  const rows = currentLedgerRows();
  return Array.isArray(rows) ? rows : [];
}

function makeCurrentSnapshot() {
  const ledgerRows = currentLedgerRows();
  return {
    capturedAt: new Date().toISOString(),
    items: ledgerRows.map((row) => ({
      id: row.id,
      item: row.item,
      category: row.category,
      route: row.route,
      salesVolume: asNumber(row.salesVolume),
      sellThrough: asNumber(row.sellThrough)
    }))
  };
}

function snapshotPair() {
  if (snapshots.length >= 2) {
    return {
      currentSnapshot: snapshots[snapshots.length - 1],
      baseline: snapshots[snapshots.length - 2]
    };
  }

  if (snapshots.length === 1) {
    return {
      currentSnapshot: snapshots[0],
      baseline: null
    };
  }

  return {
    currentSnapshot: makeCurrentSnapshot(),
    baseline: null
  };
}

function buildTrendRows() {
  const { currentSnapshot, baseline } = snapshotPair();
  const historyById = new Map();

  snapshots.forEach((snapshot) => {
    snapshot.items.forEach((item) => {
      if (!historyById.has(item.id)) {
        historyById.set(item.id, []);
      }
      historyById.get(item.id).push(item.salesVolume);
    });
  });

  currentSnapshot.items.forEach((item) => {
    if (!historyById.has(item.id)) {
      historyById.set(item.id, []);
    }
    const values = historyById.get(item.id);
    if (values[values.length - 1] !== item.salesVolume) {
      values.push(item.salesVolume);
    }
  });

  const baselineMap = new Map((baseline?.items || []).map((item) => [item.id, item]));

  return currentSnapshot.items
    .map((item) => {
      const previous = baselineMap.get(item.id);
      const previousVolume = asNumber(previous?.salesVolume);
      const currentVolume = asNumber(item.salesVolume);
      const delta = currentVolume - previousVolume;
      const percentChange = previousVolume > 0 ? (delta / previousVolume) * 100 : currentVolume > 0 ? 100 : 0;
      const sellThrough = asNumber(item.sellThrough);
      const momentum = computeMomentum(delta, percentChange, sellThrough);
      const pattern = sparkline(historyById.get(item.id) || [currentVolume]);

      return {
        ...item,
        previousVolume,
        currentVolume,
        delta,
        percentChange,
        sellThrough,
        momentum,
        pattern,
        lastUpdate: currentSnapshot.capturedAt
      };
    })
    .sort((left, right) => right.momentum - left.momentum || right.delta - left.delta);
}

function computeMomentum(delta, percentChange, sellThrough) {
  const normalizedDelta = Math.max(-20, Math.min(20, delta)) * 2;
  const normalizedPercent = Math.max(-100, Math.min(100, percentChange)) * 0.2;
  const normalizedSellThrough = Math.max(0, Math.min(50, sellThrough)) * 0.6;
  return Math.round(normalizedDelta + normalizedPercent + normalizedSellThrough);
}

function sparkline(values) {
  const bars = "▁▂▃▄▅▆▇█";
  const numeric = values.map((value) => asNumber(value));
  const min = Math.min(...numeric);
  const max = Math.max(...numeric);

  if (min === max) {
    return numeric.map(() => bars[3]).join("");
  }

  return numeric
    .map((value) => {
      const ratio = (value - min) / (max - min);
      const index = Math.min(bars.length - 1, Math.floor(ratio * (bars.length - 1)));
      return bars[index];
    })
    .join("");
}

function visibleTrendRows() {
  const rows = buildTrendRows();
  const query = trendSearchInput.value.trim().toLowerCase();
  const direction = trendFilter.value;

  return rows.filter((row) => {
    const haystack = `${row.item} ${row.category} ${row.route}`.toLowerCase();
    const matchesSearch = !query || haystack.includes(query);
    const matchesDirection =
      direction === "ALL" ||
      (direction === "UP" && row.delta > 0) ||
      (direction === "FLAT" && row.delta === 0) ||
      (direction === "DOWN" && row.delta < 0);

    return matchesSearch && matchesDirection;
  });
}

function isHighVolumeTrend(row) {
  return row.delta > 0 && row.currentVolume >= 25;
}

function discoverySnapshotPair() {
  if (liveDiscoverySnapshots.length >= 2) {
    return {
      currentSnapshot: liveDiscoverySnapshots[liveDiscoverySnapshots.length - 1],
      baseline: liveDiscoverySnapshots[liveDiscoverySnapshots.length - 2]
    };
  }

  if (liveDiscoverySnapshots.length === 1) {
    return {
      currentSnapshot: liveDiscoverySnapshots[0],
      baseline: null
    };
  }

  return {
    currentSnapshot: {
      capturedAt: "",
      items: liveDiscoveryProducts.map((product) => ({
        id: product.id,
        item: product.item,
        category: product.category,
        route: "Discovery",
        salesVolume: product.currentVolume,
        avgSalePrice: product.avgSalePrice
      }))
    },
    baseline: null
  };
}

function buildDiscoveryRows() {
  const { currentSnapshot, baseline } = discoverySnapshotPair();
  const baselineMap = new Map((baseline?.items || []).map((item) => [item.id, item]));
  const liveMap = new Map(liveDiscoveryProducts.map((product) => [product.id, product]));

  return currentSnapshot.items
    .map((item) => {
      const previous = baselineMap.get(item.id);
      const liveProduct = liveMap.get(item.id) || {};
      const currentVolume = asNumber(item.salesVolume);
      const previousVolume = asNumber(previous?.salesVolume);
      const delta = currentVolume - previousVolume;
      const percentChange = previousVolume > 0 ? (delta / previousVolume) * 100 : currentVolume > 0 ? 100 : 0;
      const avgSalePrice = asNumber(item.avgSalePrice || liveProduct.avgSalePrice);
      const momentum =
        Math.round(
          Math.max(-20, Math.min(20, delta)) * 2 +
          Math.max(-100, Math.min(100, percentChange)) * 0.2 +
          Math.max(0, Math.min(400, currentVolume)) * 0.15
        );

      return {
        id: item.id,
        item: item.item,
        category: item.category,
        route: "Discovery",
        currentVolume,
        previousVolume,
        delta,
        percentChange,
        avgSalePrice,
        momentum,
        sampleTitles: liveProduct.sampleTitles || [],
        seedQueries: liveProduct.seedQueries || [],
        lastSold: liveProduct.lastSold || "",
        lastUpdate: currentSnapshot.capturedAt
      };
    })
    .sort((left, right) => {
      if (right.currentVolume !== left.currentVolume) return right.currentVolume - left.currentVolume;
      if (right.delta !== left.delta) return right.delta - left.delta;
      return right.momentum - left.momentum;
    });
}

function highVolumeDiscoveryRows() {
  return buildDiscoveryRows().filter((row) => row.currentVolume >= 50);
}

function visibleDiscoveryRows() {
  const query = trendSearchInput.value.trim().toLowerCase();
  return highVolumeDiscoveryRows().filter((row) => {
    const haystack = `${row.item} ${row.category} ${row.route} ${row.seedQueries.join(" ")} ${row.sampleTitles.join(" ")}`.toLowerCase();
    return !query || haystack.includes(query);
  });
}

function deltaClass(delta) {
  if (delta > 0) return "trend-up";
  if (delta < 0) return "trend-down";
  return "trend-flat";
}

function render() {
  const rows = visibleTrendRows();
  syncControlState();
  renderTable(rows);
  renderTopMovers(rows);
  renderSummary(buildTrendRows());
  renderDiscoveryPanel();
  renderActionState(rows);
}

function renderTable(rows) {
  if (!rows.length) {
    trendTableBody.innerHTML = `
      <tr>
        <td colspan="11">
          <div class="empty-state">No rows match the current trend filter.</div>
        </td>
      </tr>
    `;
    return;
  }

  trendTableBody.innerHTML = rows
    .map((row) => `
      <tr>
        <td class="row-item">
          <strong>${escapeHtml(row.item)}</strong>
          <small>${escapeHtml(row.category)} · ${escapeHtml(row.route)}</small>
        </td>
        <td>${escapeHtml(row.category)}</td>
        <td>${escapeHtml(row.route)}</td>
        <td class="numeric">${row.currentVolume}</td>
        <td class="numeric">${row.previousVolume}</td>
        <td class="numeric ${deltaClass(row.delta)}">${formatDelta(row.delta)}</td>
        <td class="numeric ${deltaClass(row.delta)}">${formatPercentChange(row.percentChange)}</td>
        <td class="numeric">${formatPlainPercent(row.sellThrough)}</td>
        <td><span class="score-pill">${row.momentum}</span></td>
        <td class="numeric"><span class="sparkline">${row.pattern}</span></td>
        <td class="numeric">${formatDateTime(row.lastUpdate)}</td>
      </tr>
    `)
    .join("");
}

function renderTopMovers(rows) {
  const topRows = rows.filter((row) => row.delta > 0).slice(0, 5);

  if (!topRows.length) {
    topMoversList.innerHTML = `<div class="empty-state">No rising items in the current filter.</div>`;
    return;
  }

  topMoversList.innerHTML = topRows
    .map((row) => `
      <article class="candidate">
        <h3>${escapeHtml(row.item)}</h3>
        <p>
          ${escapeHtml(row.category)} · ${escapeHtml(row.route)}<br />
          Volume ${row.previousVolume} -> ${row.currentVolume} ·
          Delta ${formatDelta(row.delta)} · Momentum ${row.momentum}
        </p>
      </article>
    `)
    .join("");
}

function renderSummary(rows) {
  const upRows = rows.filter((row) => row.delta > 0);
  const fastestMover = upRows[0];
  const largestGain = upRows.reduce((max, row) => Math.max(max, row.delta), 0);
  const averageMomentum =
    rows.reduce((sum, row) => sum + row.momentum, 0) / Math.max(rows.length, 1);
  const lastSnapshot = snapshots[snapshots.length - 1]?.capturedAt || "";

  summaryTargets.trendingUp.textContent = String(upRows.length);
  summaryTargets.fastestMover.textContent = fastestMover ? fastestMover.item : "None";
  summaryTargets.largestGain.textContent = largestGain > 0 ? `+${largestGain}` : "0";
  summaryTargets.avgMomentum.textContent = averageMomentum.toFixed(0);
  summaryTargets.lastSnapshot.textContent = formatDateTime(lastSnapshot);
}

function renderActionState(rows) {
  if (!highVolumeMode) {
    trendActionState.textContent = trendActionMessage;
    return;
  }

  const discoveryRows = visibleDiscoveryRows();
  if (!discoveryRows.length) {
    trendActionState.textContent =
      "No discovered products match the current search and high-volume rule.";
    return;
  }

  const names = discoveryRows.slice(0, 3).map((row) => row.item).join(", ");
  const summary =
    `Market-trend feed active. Showing ${discoveryRows.length} discovered product${discoveryRows.length === 1 ? "" : "s"}: ${names}.`;
  trendActionState.textContent = trendActionMessage ? `${trendActionMessage} ${summary}` : summary;
}

function renderDiscoveryPanel() {
  if (!highVolumeMode) {
    discoveryPanel.hidden = true;
    discoveryResultsList.innerHTML = "";
    return;
  }

  discoveryPanel.hidden = false;
  const rows = visibleDiscoveryRows();
  if (!rows.length) {
    discoveryResultsList.innerHTML = `<div class="empty-state">No discovered products match the current search and high-volume rule.</div>`;
    return;
  }

  discoveryResultsList.innerHTML = rows
    .slice(0, 12)
    .map((row) => {
      const sample = row.sampleTitles[0] ? escapeHtml(row.sampleTitles[0]) : "No sample title captured.";
      const seedText = row.seedQueries.length ? row.seedQueries.join(", ") : "discovery seed";
      const alreadyTracked = isTrackedProduct(row);
      return `
        <article class="discovery-card">
          <h3>${escapeHtml(row.item)}</h3>
          <p>
            ${escapeHtml(row.category)} · ${escapeHtml(seedText)}<br />
            Volume ${row.currentVolume}
            ${row.previousVolume > 0 ? `· Delta ${formatDelta(row.delta)} (${formatPercentChange(row.percentChange)})` : ""}
            · Avg sale $${row.avgSalePrice.toFixed(2)}
          </p>
          <p>${sample}</p>
          <div class="discovery-card-actions">
            <button
              type="button"
              class="secondary"
              data-add-trend-item="${escapeHtml(row.id)}"
              ${alreadyTracked ? "disabled" : ""}
            >
              ${alreadyTracked ? "Promoted" : "Promote to Ledger"}
            </button>
          </div>
        </article>
      `;
    })
    .join("");
}

function isTrackedProduct(product) {
  return currentTrackedList().some((row) => row.id === product.id || row.item === product.item);
}

function saleEvidenceUrlForProduct(product) {
  const query = encodeURIComponent(product.item).replace(/%20/g, "+");
  return `https://www.ebay.com/sh/research?marketplace=EBAY-US&keywords=${query}&dayRange=30&tabName=SOLD&tz=America%2FLos_Angeles`;
}

function addDiscoveryProductToList(productId) {
  const product = buildDiscoveryRows().find((row) => row.id === productId);
  if (!product) {
    trendActionMessage = "Could not find that discovered product in the current feed.";
    render();
    return;
  }

  const trackedRows = currentTrackedList();
  if (trackedRows.some((row) => row.id === product.id || row.item === product.item)) {
    trendActionMessage = `${product.item} is already in your tracked list.`;
    render();
    return;
  }

  const nextRows = [
    {
      id: product.id,
      item: product.item,
      category: product.category,
      route: "eBay",
      researchDate: new Date().toISOString().slice(0, 10),
      researchWindow: "Last 30 Days",
      avgSalePrice: product.avgSalePrice,
      salesVolume: product.currentVolume,
      sellThrough: 0,
      totalSellers: 0,
      buyingPrice: 0,
      fees: 0,
      shipping: 0,
      supplies: 0,
      saleEvidenceUrl: saleEvidenceUrlForProduct(product),
      buyEvidenceUrl: "",
      decisionStatus: "NEEDS_PRICE",
      nextAction: "Attach buy-side pricing before considering purchase",
      notes: `Promoted from market trends feed. Seeds: ${product.seedQueries.join(", ") || "discovery"}.`
    },
    ...trackedRows
  ];

  window.localStorage.setItem(LEDGER_STORAGE_KEY, JSON.stringify(nextRows));
  trendActionMessage = `${product.item} promoted to the ledger for pricing. Open the Ledger view to finish the evaluation.`;
  render();
}

function captureSnapshot() {
  const snapshot = makeCurrentSnapshot();
  snapshots = [...snapshots, snapshot];
  persistSnapshots();
  render();
}

function resetSnapshots() {
  if (!window.confirm("Reset trend snapshot history to the current live seed snapshots?")) {
    return;
  }

  snapshots = cloneSeedSnapshots();
  persistSnapshots();
  trendActionMessage = "Snapshot history reset to the current live seed snapshots.";
  render();
}

async function refreshLiveData() {
  if (!refreshDataButton || refreshDataButton.disabled) {
    return;
  }

  const previousGeneratedAt = currentGeneratedAt();
  const originalLabel = refreshDataButton.textContent;
  setRefreshButtonsDisabled(true);
  refreshDataButton.textContent = "Refreshing...";
  trendActionMessage = "Refreshing live data from the latest generated research file...";
  render();

  try {
    await loadLatestLiveDataScript();
    refreshLiveBindings();
    snapshots = loadSnapshots();
    persistSnapshots();

    const latestGeneratedAt = currentGeneratedAt();
    const changed = latestGeneratedAt && latestGeneratedAt !== previousGeneratedAt;
    trendActionMessage = latestGeneratedAt
      ? changed
        ? `Live data refreshed. New research file generated ${formatDateTime(latestGeneratedAt)}.`
        : `Live data reloaded. Current research file generated ${formatDateTime(latestGeneratedAt)}.`
      : "Live data reloaded.";
    render();
  } catch (error) {
    trendActionMessage = error.message || "Refresh failed.";
    render();
  } finally {
    setRefreshButtonsDisabled(false);
    refreshDataButton.textContent = originalLabel;
  }
}

async function runFreshPull() {
  if (!supportsFreshPull()) {
    trendActionMessage = "Run Fresh Pull requires the local Sales OS server. Open the app over http://localhost.";
    render();
    return;
  }

  if (!runFreshPullButton || runFreshPullButton.disabled) {
    return;
  }

  const originalRunLabel = runFreshPullButton.textContent;
  const originalRefreshLabel = refreshDataButton ? refreshDataButton.textContent : "";
  setRefreshButtonsDisabled(true);
  runFreshPullButton.textContent = "Pulling...";
  if (refreshDataButton) {
    refreshDataButton.textContent = "Waiting...";
  }
  trendActionMessage = "Running Seller Hub refresh. This can take a minute while Chrome pulls new research data...";
  render();

  try {
    const response = await fetch("/api/run-refresh", {
      method: "POST",
      headers: {
        Accept: "application/json"
      }
    });
    const payload = await response.json();

    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || payload.details || "Fresh pull failed.");
    }

    await loadLatestLiveDataScript();
    refreshLiveBindings();
    snapshots = loadSnapshots();
    persistSnapshots();

    const generatedAt = payload.generatedAt || currentGeneratedAt();
    const durationText = payload.durationSeconds ? ` in ${payload.durationSeconds}s` : "";
    trendActionMessage = generatedAt
      ? `Fresh pull complete${durationText}. New research file generated ${formatDateTime(generatedAt)}.`
      : `Fresh pull complete${durationText}.`;
    render();
  } catch (error) {
    trendActionMessage = error.message || "Fresh pull failed.";
    render();
  } finally {
    setRefreshButtonsDisabled(false);
    runFreshPullButton.textContent = originalRunLabel;
    if (refreshDataButton) {
      refreshDataButton.textContent = originalRefreshLabel;
    }
  }
}

function toggleHighVolumeMode() {
  highVolumeMode = !highVolumeMode;
  syncControlState();
  render();
}

function syncControlState() {
  if (highVolumeMode) {
    showHighVolumeButton.textContent = "Show Watchlist Trends";
    return;
  }

  showHighVolumeButton.textContent = "Show Trending Products";
}

trendFilter.addEventListener("change", render);
trendSearchInput.addEventListener("input", render);
runFreshPullButton.addEventListener("click", runFreshPull);
refreshDataButton.addEventListener("click", refreshLiveData);
showHighVolumeButton.addEventListener("click", toggleHighVolumeMode);
captureSnapshotButton.addEventListener("click", captureSnapshot);
resetSnapshotsButton.addEventListener("click", resetSnapshots);
discoveryResultsList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-add-trend-item]");
  if (!button) {
    return;
  }
  addDiscoveryProductToList(button.getAttribute("data-add-trend-item"));
});

window.addEventListener("storage", (event) => {
  if (event.key === LEDGER_STORAGE_KEY || event.key === SNAPSHOT_STORAGE_KEY) {
    snapshots = loadSnapshots();
    render();
  }
});

setInterval(() => {
  render();
}, 15000);

highVolumeMode = true;
persistSnapshots();
const initialGeneratedAt = currentGeneratedAt();
if (initialGeneratedAt) {
  trendActionMessage = `Live data loaded from research file generated ${formatDateTime(initialGeneratedAt)}.`;
} else if (!supportsFreshPull()) {
  trendActionMessage = "Run Fresh Pull is available when the app is opened through the local Sales OS server.";
}
render();
