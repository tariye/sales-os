const STORAGE_KEY = "sales-os-demand-ledger";

const defaultSeedRows = [
  {
    id: "imac-2011",
    item: "iMac 21.5 2011",
    category: "Computers",
    route: "FB Local",
    researchDate: "2026-07-03",
    researchWindow: "Last 30 Days",
    avgSalePrice: 111.42,
    salesVolume: 24,
    sellThrough: 4.01,
    totalSellers: 18,
    buyingPrice: 40,
    fees: 0,
    shipping: 0,
    supplies: 0,
    saleEvidenceUrl: "https://www.ebay.com/sh/research?marketplace=EBAY-US&keywords=iMac+21.5+2011&dayRange=30&endDate=1783136824342&startDate=1780544824342&categoryId=111418&tabName=SOLD&tz=America%2FLos_Angeles",
    buyEvidenceUrl: "./evidence.html#imac-2011-buy",
    notes: "Live Product Research sold metric. Local route still preferred for bulky desktops."
  },
  {
    id: "macbook-pro-2012",
    item: "2012 MacBook Pro 13",
    category: "Computers",
    route: "Both",
    researchDate: "2026-07-03",
    researchWindow: "Last 30 Days",
    avgSalePrice: 118.92,
    salesVolume: 272,
    sellThrough: 16.48,
    totalSellers: 152,
    buyingPrice: 45,
    fees: 18,
    shipping: 18,
    supplies: 3,
    saleEvidenceUrl: "https://www.ebay.com/sh/research?marketplace=EBAY-US&keywords=2012+MacBook+Pro+13&dayRange=30&endDate=1783136824342&startDate=1780544824342&categoryId=111422&tabName=SOLD&tz=America%2FLos_Angeles",
    buyEvidenceUrl: "./evidence.html#macbook-pro-2012-buy",
    notes: "Live Product Research sold metric in Apple Laptops."
  },
  {
    id: "altima-door-handle",
    item: "Nissan Altima Driver Door Handle",
    category: "Auto Parts",
    route: "eBay",
    researchDate: "2026-07-03",
    researchWindow: "Last 30 Days",
    avgSalePrice: 19.49,
    salesVolume: 55,
    sellThrough: 14.8,
    totalSellers: 25,
    buyingPrice: 6,
    fees: 3,
    shipping: 5,
    supplies: 1,
    saleEvidenceUrl: "https://www.ebay.com/sh/research?marketplace=EBAY-US&keywords=Nissan+Altima+driver+door+handle&dayRange=30&endDate=1783136824342&startDate=1780544824342&categoryId=179851&tabName=SOLD&tz=America%2FLos_Angeles",
    buyEvidenceUrl: "./evidence.html#altima-door-handle-buy",
    notes: "Live Product Research sold metric in Door Handles."
  },
  {
    id: "altima-cluster",
    item: "Nissan Altima Instrument Cluster",
    category: "Auto Parts",
    route: "eBay",
    researchDate: "2026-07-03",
    researchWindow: "Last 30 Days",
    avgSalePrice: 70.72,
    salesVolume: 62,
    sellThrough: 19.02,
    totalSellers: 38,
    buyingPrice: 20,
    fees: 9,
    shipping: 12,
    supplies: 2,
    saleEvidenceUrl: "https://www.ebay.com/sh/research?marketplace=EBAY-US&keywords=Nissan+Altima+instrument+cluster&dayRange=30&endDate=1783136824342&startDate=1780544824342&categoryId=33675&tabName=SOLD&tz=America%2FLos_Angeles",
    buyEvidenceUrl: "./evidence.html#altima-cluster-buy",
    notes: "Live Product Research sold metric in Instrument Clusters."
  },
  {
    id: "raspberry-pi-4-4gb",
    item: "Raspberry Pi 4 Model B 4GB",
    category: "Compute Boards",
    route: "eBay",
    researchDate: "2026-07-03",
    researchWindow: "Last 30 Days",
    avgSalePrice: 57,
    salesVolume: 8,
    sellThrough: 47.06,
    totalSellers: 8,
    buyingPrice: 30,
    fees: 8,
    shipping: 6,
    supplies: 1,
    saleEvidenceUrl: "https://www.ebay.com/sh/research?marketplace=EBAY-US&keywords=Raspberry+Pi+4+Model+B+4GB&dayRange=30&endDate=1783136824342&startDate=1780544824342&categoryId=65507&tabName=SOLD&tz=America%2FLos_Angeles",
    buyEvidenceUrl: "./evidence.html#raspberry-pi-4-4gb-buy",
    notes: "Live Product Research sold metric in Development Kits & Boards."
  },
  {
    id: "raspberry-pi-5-8gb",
    item: "Raspberry Pi 5 8GB",
    category: "Compute Boards",
    route: "eBay",
    researchDate: "2026-07-03",
    researchWindow: "Last 30 Days",
    avgSalePrice: 125.14,
    salesVolume: 11,
    sellThrough: 25,
    totalSellers: 10,
    buyingPrice: 70,
    fees: 17,
    shipping: 7,
    supplies: 1,
    saleEvidenceUrl: "https://www.ebay.com/sh/research?marketplace=EBAY-US&keywords=Raspberry+Pi+5+8GB&dayRange=30&endDate=1783136824342&startDate=1780544824342&categoryId=65507&tabName=SOLD&tz=America%2FLos_Angeles",
    buyEvidenceUrl: "./evidence.html#raspberry-pi-5-8gb-buy",
    notes: "Live Product Research sold metric in Development Kits & Boards."
  },
  {
    id: "jetson-nano",
    item: "NVIDIA Jetson Nano Developer Kit",
    category: "Compute Boards",
    route: "eBay",
    researchDate: "2026-07-03",
    researchWindow: "Last 30 Days",
    avgSalePrice: 234.59,
    salesVolume: 16,
    sellThrough: 27.27,
    totalSellers: 11,
    buyingPrice: 110,
    fees: 32,
    shipping: 12,
    supplies: 2,
    saleEvidenceUrl: "https://www.ebay.com/sh/research?marketplace=EBAY-US&keywords=NVIDIA+Jetson+Nano+Developer+Kit&dayRange=30&endDate=1783136824342&startDate=1780544824342&categoryId=65507&tabName=SOLD&tz=America%2FLos_Angeles",
    buyEvidenceUrl: "./evidence.html#jetson-nano-buy",
    notes: "Live Product Research sold metric in Development Kits & Boards."
  },
  {
    id: "beaglebone-black",
    item: "BeagleBone Black",
    category: "Compute Boards",
    route: "eBay",
    researchDate: "2026-07-03",
    researchWindow: "Last 30 Days",
    avgSalePrice: 31.35,
    salesVolume: 28,
    sellThrough: 35.48,
    totalSellers: 18,
    buyingPrice: 12,
    fees: 4,
    shipping: 6,
    supplies: 1,
    saleEvidenceUrl: "https://www.ebay.com/sh/research?marketplace=EBAY-US&keywords=BeagleBone+Black&dayRange=30&endDate=1783136824342&startDate=1780544824342&categoryId=65507&tabName=SOLD&tz=America%2FLos_Angeles",
    buyEvidenceUrl: "./evidence.html#beaglebone-black-buy",
    notes: "Live Product Research sold metric in Development Kits & Boards."
  }
];

const decisionFilter = document.querySelector("#decisionFilter");
const searchInput = document.querySelector("#searchInput");
const ledgerTableBody = document.querySelector("#ledgerTableBody");
const buyCandidatesList = document.querySelector("#buyCandidatesList");
const itemForm = document.querySelector("#itemForm");
const runFreshPullButton = document.querySelector("#runFreshPullButton");
const refreshDataButton = document.querySelector("#refreshDataButton");
const exportCsvButton = document.querySelector("#exportCsvButton");
const resetButton = document.querySelector("#resetButton");
const ledgerActionState = document.querySelector("#ledgerActionState");

const summaryTargets = {
  trackedItems: document.querySelector("#trackedItemsValue"),
  buyCandidates: document.querySelector("#buyCandidatesValue"),
  avgNetMargin: document.querySelector("#avgNetMarginValue"),
  expectedNet: document.querySelector("#expectedNetValue"),
  strongestCluster: document.querySelector("#strongestClusterValue")
};
const marginPreview = document.querySelector("#marginPreview");

let liveSeedRows = [];
let seedRows = defaultSeedRows;
let seedRowMap = new Map(defaultSeedRows.map((row) => [row.id, row]));
let ledgerActionMessage = "";

refreshLiveSeedRows();
let rows = loadRows();

function cloneSeedRows() {
  if (typeof structuredClone === "function") {
    return structuredClone(seedRows);
  }

  return JSON.parse(JSON.stringify(seedRows));
}

function loadRows() {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (!stored) {
    return cloneSeedRows();
  }

  try {
    const parsed = JSON.parse(stored);
    const hydratedSeedRows = parsed
      .filter((row) => seedRowMap.has(row.id))
      .map((row) => hydrateRow(row));
    const storedCustomRows = customRowsFromStorage(parsed);

    return mergeBaseAndHydratedRows(cloneSeedRows(), hydratedSeedRows, storedCustomRows);
  } catch (_error) {
    return cloneSeedRows();
  }
}

function persistRows() {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(rows));
}

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

function refreshLiveSeedRows() {
  const liveData = currentLiveData();
  liveSeedRows =
    liveData && Array.isArray(liveData.ledgerRows)
      ? liveData.ledgerRows
      : [];
  seedRows = liveSeedRows.length ? liveSeedRows : defaultSeedRows;
  seedRowMap = new Map(seedRows.map((row) => [row.id, row]));
}

function formatDateTime(value) {
  if (!value) {
    return "unknown time";
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
}

function setLedgerActionMessage(message) {
  ledgerActionMessage = message;
  if (ledgerActionState) {
    ledgerActionState.textContent = message;
  }
}

function setRefreshButtonsDisabled(disabled) {
  if (runFreshPullButton) {
    runFreshPullButton.disabled = disabled || !supportsFreshPull();
  }

  if (refreshDataButton) {
    refreshDataButton.disabled = disabled;
  }
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

function asNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function hydrateRow(row) {
  const seedRow = seedRowMap.get(row.id);
  if (!seedRow) {
    return row;
  }

  return {
    ...seedRow,
    route: row.route || seedRow.route,
    trendKeyword: row.trendKeyword || seedRow.trendKeyword || "",
    trendWindow: row.trendWindow || seedRow.trendWindow || "",
    trendDirection: row.trendDirection || seedRow.trendDirection || "",
    trendScore: hasValue(row.trendScore) ? asNumber(row.trendScore) : asNumber(seedRow.trendScore),
    trendEvidenceUrl: row.trendEvidenceUrl || seedRow.trendEvidenceUrl || "",
    localSource: row.localSource || seedRow.localSource || "",
    localCompCount: hasValue(row.localCompCount) ? asNumber(row.localCompCount) : asNumber(seedRow.localCompCount),
    localAvgPrice: hasValue(row.localAvgPrice) ? asNumber(row.localAvgPrice) : asNumber(seedRow.localAvgPrice),
    localEvidenceUrl: row.localEvidenceUrl || seedRow.localEvidenceUrl || "",
    buyerSalesTax: hasValue(row.buyerSalesTax) ? asNumber(row.buyerSalesTax) : asNumber(seedRow.buyerSalesTax),
    buyerTotalPaid: hasValue(row.buyerTotalPaid) ? asNumber(row.buyerTotalPaid) : asNumber(seedRow.buyerTotalPaid),
    transactionFeeRate: hasValue(row.transactionFeeRate) ? asNumber(row.transactionFeeRate) : asNumber(seedRow.transactionFeeRate),
    buyerPersona: row.buyerPersona || seedRow.buyerPersona || "",
    buyerProblem: row.buyerProblem || seedRow.buyerProblem || "",
    desiredOutcome: row.desiredOutcome || seedRow.desiredOutcome || "",
    buyerFriction: row.buyerFriction || seedRow.buyerFriction || "",
    honestUseCase: row.honestUseCase || seedRow.honestUseCase || "",
    nextAction: row.nextAction || seedRow.nextAction || "",
    outcomeStatus: row.outcomeStatus || seedRow.outcomeStatus || "",
    decisionStatus: row.decisionStatus || seedRow.decisionStatus || "",
    exceptionReason: row.exceptionReason || seedRow.exceptionReason || "",
    desiredProfit: hasValue(row.desiredProfit) ? asNumber(row.desiredProfit) : asNumber(seedRow.desiredProfit),
    buyingPrice: hasValue(row.buyingPrice) ? asNumber(row.buyingPrice) : seedRow.buyingPrice,
    fees: hasValue(row.fees) ? asNumber(row.fees) : seedRow.fees,
    shipping: hasValue(row.shipping) ? asNumber(row.shipping) : seedRow.shipping,
    supplies: hasValue(row.supplies) ? asNumber(row.supplies) : seedRow.supplies,
    buyEvidenceUrl: row.buyEvidenceUrl || seedRow.buyEvidenceUrl || "",
    notes: row.notes || seedRow.notes || ""
  };
}

function customRowsFromStorage(storedRows) {
  return storedRows.filter((row) => !seedRowMap.has(row.id));
}

function hasValue(value) {
  return value !== undefined && value !== null && value !== "";
}

function mergeBaseAndHydratedRows(baseRows, hydratedRows, customRows) {
  const byId = new Map(baseRows.map((row) => [row.id, row]));
  hydratedRows.forEach((row) => {
    byId.set(row.id, row);
  });
  return [...byId.values(), ...customRows];
}

function formatCurrency(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  }).format(asNumber(value));
}

function formatPercent(value) {
  return `${(asNumber(value) * 100).toFixed(1)}%`;
}

function formatPlainPercent(value) {
  return `${asNumber(value).toFixed(2)}%`;
}

function transactionFeeAmount(row) {
  const feeAmount = asNumber(row.fees);
  if (feeAmount > 0) {
    return feeAmount;
  }

  const salePrice = asNumber(row.avgSalePrice);
  const feeRate = asNumber(row.transactionFeeRate);
  return feeRate > 0 ? salePrice * (feeRate / 100) : 0;
}

function netPayout(row) {
  return (
    asNumber(row.avgSalePrice) -
    transactionFeeAmount(row) -
    asNumber(row.shipping) -
    asNumber(row.supplies)
  );
}

function payoutRate(row) {
  const salePrice = asNumber(row.avgSalePrice);
  return salePrice ? netPayout(row) / salePrice : 0;
}

function sellingCostRate(row) {
  const salePrice = asNumber(row.avgSalePrice);
  if (!salePrice) {
    return 0;
  }

  return (transactionFeeAmount(row) + asNumber(row.shipping) + asNumber(row.supplies)) / salePrice;
}

function desiredProfitTarget(row) {
  return hasValue(row.desiredProfit) ? asNumber(row.desiredProfit) : 20;
}

function maxBuyPrice(row) {
  return netPayout(row) - desiredProfitTarget(row);
}

function netProfit(row) {
  return netPayout(row) - asNumber(row.buyingPrice);
}

function netMargin(row) {
  const salePrice = asNumber(row.avgSalePrice);
  if (!salePrice) {
    return 0;
  }

  return netProfit(row) / salePrice;
}

function needsBuyPrice(row) {
  const hasBuySideCost =
    asNumber(row.buyingPrice) > 0 ||
    asNumber(row.fees) > 0 ||
    asNumber(row.shipping) > 0 ||
    asNumber(row.supplies) > 0;
  const hasBuyEvidence = Boolean((row.buyEvidenceUrl || "").trim());
  const demandSignals =
    asNumber(row.salesVolume) > 0 ||
    asNumber(row.trendScore) > 0 ||
    asNumber(row.localCompCount) > 0 ||
    Boolean((row.saleEvidenceUrl || "").trim()) ||
    Boolean((row.trendKeyword || "").trim()) ||
    Boolean((row.localSource || "").trim()) ||
    Boolean((row.buyerPersona || "").trim()) ||
    Boolean((row.buyerProblem || "").trim()) ||
    Boolean((row.honestUseCase || "").trim()) ||
    Boolean((row.notes || "").trim());
  const forcedNeedsPrice =
    (row.decisionStatus || "").toUpperCase() === "NEEDS_PRICE" &&
    !hasBuySideCost &&
    !hasBuyEvidence;

  return forcedNeedsPrice || (!hasBuySideCost && !hasBuyEvidence && demandSignals);
}

function isManualDecision(row) {
  const decisionStatus = (row.decisionStatus || "").toUpperCase();
  return ["WATCH", "EXCEPTION"].includes(decisionStatus);
}

function isWatchOpportunity(row) {
  const volume = asNumber(row.salesVolume);
  const trendScore = asNumber(row.trendScore);
  const sellThrough = asNumber(row.sellThrough);
  const localCompCount = asNumber(row.localCompCount);
  const hasBuyerIntel = [
    row.buyerPersona,
    row.buyerProblem,
    row.desiredOutcome,
    row.buyerFriction,
    row.honestUseCase
  ].some((value) => Boolean(String(value || "").trim()));
  const hasDemandSignals =
    volume >= 5 &&
    (trendScore >= 50 ||
      localCompCount > 0 ||
      sellThrough >= 15 ||
      Boolean(String(row.trendKeyword || "").trim()));

  return hasDemandSignals && hasBuyerIntel;
}

function decision(row) {
  const override = (row.decisionStatus || "").toUpperCase();
  if (override === "WATCH" || override === "EXCEPTION") {
    return override;
  }

  if (needsBuyPrice(row)) {
    return "NEEDS_PRICE";
  }

  if (
    netProfit(row) >= 20 &&
    netMargin(row) >= 0.3 &&
    asNumber(row.salesVolume) >= 5
  ) {
    return "BUY";
  }

  if (isWatchOpportunity(row)) {
    return "WATCH";
  }

  return "PASS";
}

function decisionLabel(value) {
  return value === "NEEDS_PRICE" ? "NEEDS PRICE" : value;
}

function decisionClass(value) {
  if (value === "BUY") return "decision-buy";
  if (value === "NEEDS_PRICE") return "decision-needs-price";
  if (value === "WATCH") return "decision-watch";
  if (value === "EXCEPTION") return "decision-exception";
  return "decision-pass";
}

function buyerIntelSummary(row) {
  const parts = [];
  if ((row.buyerPersona || "").trim()) {
    parts.push(row.buyerPersona.trim());
  }
  if ((row.buyerProblem || "").trim()) {
    parts.push(row.buyerProblem.trim());
  }
  if ((row.honestUseCase || "").trim()) {
    parts.push(`Use case: ${row.honestUseCase.trim()}`);
  }
  if ((row.buyerFriction || "").trim()) {
    parts.push(`Risk: ${row.buyerFriction.trim()}`);
  }
  if ((row.desiredOutcome || "").trim()) {
    parts.push(`Outcome: ${row.desiredOutcome.trim()}`);
  }
  return parts.length ? parts.join(" · ") : "No buyer intel captured";
}

function nextActionText(row) {
  return (
    (row.nextAction || "").trim() ||
    (decision(row) === "NEEDS_PRICE"
      ? "Attach buy-side pricing before considering purchase"
      : decision(row) === "WATCH"
        ? "Keep watching demand and gather more evidence"
        : decision(row) === "EXCEPTION"
          ? "Review exception note and validate the override"
          : "No next action captured")
  );
}

function signalScore(row) {
  const volume = asNumber(row.salesVolume);
  const sellThrough = asNumber(row.sellThrough);
  const salePrice = asNumber(row.avgSalePrice);
  const sellers = asNumber(row.totalSellers);
  const margin = netMargin(row);

  const score =
    scoreBand(volume, [5, 15, 40, 80]) +
    scoreBand(sellThrough, [5, 10, 20, 35]) +
    scoreBand(salePrice, [20, 50, 100, 175]) +
    reverseScoreBand(sellers, [15, 35, 75, 150]) +
    scoreBand(margin * 100, [10, 20, 30, 45]);

  return score;
}

function scoreBand(value, thresholds) {
  if (value >= thresholds[3]) return 5;
  if (value >= thresholds[2]) return 4;
  if (value >= thresholds[1]) return 3;
  if (value >= thresholds[0]) return 2;
  return value > 0 ? 1 : 0;
}

function reverseScoreBand(value, thresholds) {
  if (!value) return 0;
  if (value <= thresholds[0]) return 5;
  if (value <= thresholds[1]) return 4;
  if (value <= thresholds[2]) return 3;
  if (value <= thresholds[3]) return 2;
  return 1;
}

function visibleRows() {
  const query = searchInput.value.trim().toLowerCase();
  const filter = decisionFilter.value;

  return rows.filter((row) => {
    const rowDecision = decision(row);
    const haystack = `${row.item} ${row.category} ${row.route} ${row.trendKeyword || ""} ${row.localSource || ""} ${row.notes || ""} ${row.buyerPersona || ""} ${row.buyerProblem || ""} ${row.desiredOutcome || ""} ${row.buyerFriction || ""} ${row.honestUseCase || ""} ${row.nextAction || ""} ${row.outcomeStatus || ""} ${row.exceptionReason || ""} ${row.decisionStatus || ""}`.toLowerCase();
    const passesSearch = !query || haystack.includes(query);
    const passesFilter = filter === "ALL" || rowDecision === filter;
    return passesSearch && passesFilter;
  });
}

function render() {
  renderActionState();
  renderTable();
  renderCandidates();
  renderSummary();
  renderMarginPreview();
}

function renderActionState() {
  if (ledgerActionState) {
    ledgerActionState.textContent = ledgerActionMessage;
  }
}

function renderTable() {
  const filteredRows = visibleRows();

  if (!filteredRows.length) {
    ledgerTableBody.innerHTML = `
      <tr>
        <td colspan="18">
          <div class="empty-state">No rows match the current filter.</div>
        </td>
      </tr>
    `;
    return;
  }

  ledgerTableBody.innerHTML = filteredRows
    .map((row) => {
      const profit = netProfit(row);
      const margin = netMargin(row);
      const rowDecision = decision(row);
      const score = signalScore(row);

      return `
        <tr>
          <td class="row-item">
            <strong>${escapeHtml(row.item)}</strong>
            <small>${escapeHtml(row.notes || "No notes yet.")}</small>
          </td>
          <td>${escapeHtml(row.category)}</td>
          <td>${escapeHtml(row.route)}</td>
          <td class="numeric">${renderEvidencePrice(row.avgSalePrice, row.saleEvidenceUrl, "Sale evidence")}</td>
          <td class="numeric">${asNumber(row.salesVolume)}</td>
          <td class="numeric">${formatPlainPercent(row.sellThrough)}</td>
          <td>${renderTrendSignal(row)}</td>
          <td>${renderLocalSignal(row)}</td>
          <td class="numeric">${renderEvidencePrice(row.buyingPrice, row.buyEvidenceUrl, "Buy evidence")}</td>
          <td class="numeric">${formatCurrency(row.fees)}</td>
          <td class="numeric">${formatCurrency(row.shipping)}</td>
          <td class="numeric">${formatCurrency(row.supplies)}</td>
          <td class="numeric">${formatCurrency(profit)}</td>
          <td class="numeric">${formatPercent(margin)}</td>
          <td><span class="score-pill">${score}/25</span></td>
          <td>
            <div class="buyer-intel-cell">
              <strong>${escapeHtml((row.buyerPersona || "").trim() || "Not captured")}</strong>
              <span>${escapeHtml(buyerIntelSummary(row))}</span>
            </div>
          </td>
          <td class="buyer-action-cell">${escapeHtml(nextActionText(row))}</td>
          <td>
            <span class="decision-pill ${decisionClass(rowDecision)}">
              ${decisionLabel(rowDecision)}
            </span>
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderEvidencePrice(value, evidenceUrl, evidenceLabel) {
  const price = formatCurrency(value);
  if (!evidenceUrl) {
    return `
      <div class="price-cell">
        <span class="price-value">${price}</span>
        <span class="missing-evidence">No evidence link</span>
      </div>
    `;
  }

  return `
    <div class="price-cell">
      <span class="price-value">${price}</span>
      <a class="evidence-link" href="${escapeHtml(evidenceUrl)}" target="_blank" rel="noreferrer">
        ${escapeHtml(evidenceLabel)}
      </a>
    </div>
  `;
}

function renderTrendSignal(row) {
  const keyword = (row.trendKeyword || "").trim();
  const direction = (row.trendDirection || "").trim().toUpperCase();
  const score = asNumber(row.trendScore);
  const windowLabel = (row.trendWindow || "").trim();
  const evidenceUrl = (row.trendEvidenceUrl || "").trim();

  if (!keyword && !direction && !score && !windowLabel && !evidenceUrl) {
    return `<span class="missing-evidence">No trend input</span>`;
  }

  const directionClass =
    direction === "UP" ? "trend-up" : direction === "DOWN" ? "trend-down" : "trend-flat";
  const directionLabel =
    direction === "UP" ? "Up" : direction === "DOWN" ? "Down" : direction === "FLAT" ? "Flat" : "Captured";
  const strengthLabel = score ? `Strength ${score}/100` : "Strength not set";
  const keywordText = keyword || "Google Trends";
  const detailParts = [directionLabel, strengthLabel];
  if (windowLabel) {
    detailParts.push(windowLabel);
  }

  return `
    <div class="trend-signal-cell">
      <span class="score-pill ${directionClass}">${escapeHtml(directionLabel)}</span>
      <span class="supporting-text">${escapeHtml(keywordText)}</span>
      <span class="supporting-text">${escapeHtml(detailParts.join(" · "))}</span>
      ${
        evidenceUrl
          ? `<a class="evidence-link" href="${escapeHtml(evidenceUrl)}" target="_blank" rel="noreferrer">Trend evidence</a>`
          : `<span class="missing-evidence">No evidence link</span>`
      }
    </div>
  `;
}

function renderLocalSignal(row) {
  const source = (row.localSource || "").trim();
  const count = asNumber(row.localCompCount);
  const avgPrice = asNumber(row.localAvgPrice);
  const evidenceUrl = (row.localEvidenceUrl || "").trim();

  if (!source && !count && !avgPrice && !evidenceUrl) {
    return `<span class="missing-evidence">No local comps</span>`;
  }

  const countLabel = count ? `${count} active` : "Count not set";
  const avgLabel = avgPrice ? `Avg ask ${formatCurrency(avgPrice)}` : "Avg ask not set";

  return `
    <div class="trend-signal-cell">
      <span class="score-pill">${escapeHtml(source || "Local")}</span>
      <span class="supporting-text">${escapeHtml(countLabel)}</span>
      <span class="supporting-text">${escapeHtml(avgLabel)}</span>
      ${
        evidenceUrl
          ? `<a class="evidence-link" href="${escapeHtml(evidenceUrl)}" target="_blank" rel="noreferrer">Local evidence</a>`
          : `<span class="missing-evidence">No evidence link</span>`
      }
    </div>
  `;
}

function renderCandidates() {
  const candidates = visibleRows()
    .filter((row) => decision(row) === "BUY")
    .sort((left, right) => signalScore(right) - signalScore(left));

  if (!candidates.length) {
    buyCandidatesList.innerHTML = `<div class="empty-state">No items clear the pilot rule yet.</div>`;
    return;
  }

  buyCandidatesList.innerHTML = candidates
    .map((row) => {
      const profit = netProfit(row);
      const margin = netMargin(row);

      return `
        <article class="candidate">
          <h3>${escapeHtml(row.item)}</h3>
          <p>
            ${escapeHtml(row.category)} · ${escapeHtml(row.route)}<br />
            Net ${formatCurrency(profit)} · Margin ${formatPercent(margin)} ·
            Score ${signalScore(row)}/25
            ${row.trendDirection ? ` · Trends ${escapeHtml(row.trendDirection)}` : ""}
          </p>
          <p>${escapeHtml(buyerIntelSummary(row))}</p>
          <p>${escapeHtml(nextActionText(row))}</p>
        </article>
      `;
    })
    .join("");
}

function renderSummary() {
  const buyRows = rows.filter((row) => decision(row) === "BUY");
  const watchRows = rows.filter((row) => decision(row) === "WATCH");
  const needsPriceRows = rows.filter((row) => decision(row) === "NEEDS_PRICE");
  const avgMargin =
    rows.reduce((sum, row) => sum + netMargin(row), 0) / Math.max(rows.length, 1);
  const expectedNet = buyRows.reduce((sum, row) => sum + netProfit(row), 0);
  const clusterMap = new Map();

  rows.forEach((row) => {
    const current = clusterMap.get(row.category) || 0;
    clusterMap.set(row.category, current + signalScore(row));
  });

  let strongestCluster = "None";
  let bestClusterScore = -1;
  for (const [category, score] of clusterMap.entries()) {
    if (score > bestClusterScore) {
      strongestCluster = category;
      bestClusterScore = score;
    }
  }

  summaryTargets.trackedItems.textContent = String(rows.length);
  summaryTargets.buyCandidates.textContent = String(buyRows.length);
  const watchTarget = document.querySelector("#watchCandidatesValue");
  const needsTarget = document.querySelector("#needsPriceValue");
  if (watchTarget) {
    watchTarget.textContent = String(watchRows.length);
  }
  if (needsTarget) {
    needsTarget.textContent = String(needsPriceRows.length);
  }
  summaryTargets.avgNetMargin.textContent = formatPercent(avgMargin);
  summaryTargets.expectedNet.textContent = formatCurrency(expectedNet);
  summaryTargets.strongestCluster.textContent = strongestCluster;
}

function renderMarginPreview() {
  if (!marginPreview || !itemForm) {
    return;
  }

  const formData = Object.fromEntries(new FormData(itemForm).entries());
  const salePrice = asNumber(formData.avgSalePrice);
  const explicitFee = asNumber(formData.fees);
  const feeRate = asNumber(formData.transactionFeeRate);
  const feeAmount = explicitFee > 0 ? explicitFee : salePrice * (feeRate / 100);
  const shipping = asNumber(formData.shipping);
  const supplies = asNumber(formData.supplies);
  const buyerSalesTax = asNumber(formData.buyerSalesTax);
  const buyerTotalPaid = asNumber(formData.buyerTotalPaid);
  const buyCost = asNumber(formData.buyingPrice);
  const desiredProfit = hasValue(formData.desiredProfit) ? asNumber(formData.desiredProfit) : 20;
  const transactionCost = feeAmount + shipping + supplies;
  const payout = salePrice - transactionCost;
  const payoutPct = salePrice ? payout / salePrice : 0;
  const sellingCostPct = salePrice ? transactionCost / salePrice : 0;
  const trueProfit = payout - buyCost;
  const trueProfitPct = salePrice ? trueProfit / salePrice : 0;
  const maxBuy = payout - desiredProfit;
  const hasAnyInput =
    salePrice > 0 ||
    explicitFee > 0 ||
    feeRate > 0 ||
    shipping > 0 ||
    supplies > 0 ||
    buyCost > 0 ||
    buyerSalesTax > 0 ||
    buyerTotalPaid > 0;

  marginPreview.innerHTML = `
    <div class="margin-preview-grid">
      <div><span>Sale price</span><strong>${formatCurrency(salePrice)}</strong></div>
      <div><span>Buyer sales tax</span><strong>${formatCurrency(buyerSalesTax)}</strong></div>
      <div><span>Buyer total paid</span><strong>${formatCurrency(buyerTotalPaid)}</strong></div>
      <div><span>Transaction fee</span><strong>${formatCurrency(feeAmount)}</strong></div>
      <div><span>Shipping + packaging</span><strong>${formatCurrency(shipping + supplies)}</strong></div>
      <div><span>Net payout</span><strong>${formatCurrency(payout)}</strong></div>
      <div><span>Payout rate</span><strong>${formatPercent(payoutPct)}</strong></div>
      <div><span>Selling cost rate</span><strong>${formatPercent(sellingCostPct)}</strong></div>
      <div><span>Buy cost</span><strong>${formatCurrency(buyCost)}</strong></div>
      <div><span>True profit</span><strong>${formatCurrency(trueProfit)}</strong></div>
      <div><span>Profit margin</span><strong>${formatPercent(trueProfitPct)}</strong></div>
      <div><span>Max buy price</span><strong>${formatCurrency(maxBuy)}</strong></div>
    </div>
    <p class="margin-note">
      Sales tax is not seller revenue. Use sale price only, then subtract eBay fee, shipping, packaging, and buy cost.
      Buyer total paid is tracked only as context.
    </p>
    <div class="margin-baseline">
      <span>Instrument cluster baseline</span>
      <strong>$85 sale - $13.09 fee - $5.83 shipping = $66.08 payout</strong>
      <span>Payout rate 77.7% · True profit $36.08 if buy cost is $30 · Max buy $46.08 for a $20 target profit.</span>
    </div>
    ${hasAnyInput ? "" : `<p class="margin-note">Enter sale price, fee, shipping, packaging, and buy cost to preview the margin before you add the row.</p>`}
  `;
}

function exportCsv() {
  const headers = [
    "Item",
    "Category",
    "Route",
    "Research Date",
    "Research Window",
    "Average Sale Price",
    "Sale Evidence URL",
    "Sales Volume",
    "Sell-through",
    "Total Sellers",
    "Google Trends Keyword",
    "Google Trends Window",
    "Google Trends Direction",
    "Google Trends Score",
    "Google Trends Evidence URL",
    "Local Source",
    "Local Comp Count",
    "Local Avg Ask",
    "Local Evidence URL",
    "Buyer Persona",
    "Buyer Problem",
    "Desired Outcome",
    "Buyer Friction",
    "Honest Use Case",
    "Next Action",
    "Outcome Status",
    "Decision Override",
    "Exception Reason",
    "Buying Price",
    "Buy Evidence URL",
    "Fees",
    "Shipping",
    "Supplies",
    "Net Profit",
    "Net Margin",
    "Signal Score",
    "Decision",
    "Notes"
  ];

  const lines = rows.map((row) => [
    row.item,
    row.category,
    row.route,
    row.researchDate,
    row.researchWindow,
    asNumber(row.avgSalePrice).toFixed(2),
    row.saleEvidenceUrl || "",
    asNumber(row.salesVolume).toFixed(0),
    asNumber(row.sellThrough).toFixed(2),
    asNumber(row.totalSellers).toFixed(0),
    row.trendKeyword || "",
    row.trendWindow || "",
    row.trendDirection || "",
    asNumber(row.trendScore).toFixed(0),
    row.trendEvidenceUrl || "",
    row.localSource || "",
    asNumber(row.localCompCount).toFixed(0),
    asNumber(row.localAvgPrice).toFixed(2),
    row.localEvidenceUrl || "",
    row.buyerPersona || "",
    row.buyerProblem || "",
    row.desiredOutcome || "",
    row.buyerFriction || "",
    row.honestUseCase || "",
    row.nextAction || "",
    row.outcomeStatus || "",
    row.decisionStatus || "",
    row.exceptionReason || "",
    asNumber(row.buyingPrice).toFixed(2),
    row.buyEvidenceUrl || "",
    asNumber(row.fees).toFixed(2),
    asNumber(row.shipping).toFixed(2),
    asNumber(row.supplies).toFixed(2),
    netProfit(row).toFixed(2),
    netMargin(row).toFixed(4),
    signalScore(row),
    decision(row),
    row.notes || ""
  ]);

  const csv = [headers, ...lines]
    .map((line) =>
      line
        .map((value) => `"${String(value).replaceAll('"', '""')}"`)
        .join(",")
    )
    .join("\n");

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "sales-os-demand-ledger.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function resetRows() {
  if (!window.confirm("Reset stored ledger rows to the current live seed data? This clears local edits.")) {
    return;
  }

  rows = cloneSeedRows();
  persistRows();
  setLedgerActionMessage("Stored rows reset to the current live seed data.");
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
  setLedgerActionMessage("Refreshing live data from the latest generated research file...");

  try {
    await loadLatestLiveDataScript();
    refreshLiveSeedRows();
    rows = loadRows();
    persistRows();

    const latestGeneratedAt = currentGeneratedAt();
    const changed = latestGeneratedAt && latestGeneratedAt !== previousGeneratedAt;
    const message = latestGeneratedAt
      ? changed
        ? `Live data refreshed. New research file generated ${formatDateTime(latestGeneratedAt)}.`
        : `Live data reloaded. Current research file generated ${formatDateTime(latestGeneratedAt)}.`
      : "Live data reloaded.";

    setLedgerActionMessage(message);
    render();
  } catch (error) {
    setLedgerActionMessage(error.message || "Refresh failed.");
    render();
  } finally {
    setRefreshButtonsDisabled(false);
    refreshDataButton.textContent = originalLabel;
  }
}

async function runFreshPull() {
  if (!supportsFreshPull()) {
    setLedgerActionMessage("Run Fresh Pull requires the local Sales OS server. Open the app over http://localhost.");
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
  setLedgerActionMessage("Running Seller Hub refresh. This can take a minute while Chrome pulls new research data...");
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
    refreshLiveSeedRows();
    rows = loadRows();
    persistRows();

    const generatedAt = payload.generatedAt || currentGeneratedAt();
    const durationText = payload.durationSeconds ? ` in ${payload.durationSeconds}s` : "";
    setLedgerActionMessage(
      generatedAt
        ? `Fresh pull complete${durationText}. New research file generated ${formatDateTime(generatedAt)}.`
        : `Fresh pull complete${durationText}.`
    );
    render();
  } catch (error) {
    setLedgerActionMessage(error.message || "Fresh pull failed.");
    render();
  } finally {
    setRefreshButtonsDisabled(false);
    runFreshPullButton.textContent = originalRunLabel;
    if (refreshDataButton) {
      refreshDataButton.textContent = originalRefreshLabel;
    }
  }
}

function addRow(formData) {
  rows.unshift({
    id: `${formData.item}-${Date.now()}`.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
    item: formData.item.trim(),
    category: formData.category.trim(),
    route: formData.route,
    researchDate: new Date().toISOString().slice(0, 10),
    researchWindow: "Last 30 Days",
    avgSalePrice: asNumber(formData.avgSalePrice),
    salesVolume: asNumber(formData.salesVolume),
    sellThrough: asNumber(formData.sellThrough),
    totalSellers: 0,
    trendKeyword: formData.trendKeyword.trim(),
    trendWindow: formData.trendWindow,
    trendDirection: formData.trendDirection,
    trendScore: asNumber(formData.trendScore),
    trendEvidenceUrl: formData.trendEvidenceUrl.trim(),
    localSource: formData.localSource,
    localCompCount: asNumber(formData.localCompCount),
    localAvgPrice: asNumber(formData.localAvgPrice),
    localEvidenceUrl: formData.localEvidenceUrl.trim(),
    buyerSalesTax: asNumber(formData.buyerSalesTax),
    buyerTotalPaid: asNumber(formData.buyerTotalPaid),
    transactionFeeRate: asNumber(formData.transactionFeeRate),
    buyerPersona: formData.buyerPersona.trim(),
    buyerProblem: formData.buyerProblem.trim(),
    desiredOutcome: formData.desiredOutcome.trim(),
    buyerFriction: formData.buyerFriction.trim(),
    honestUseCase: formData.honestUseCase.trim(),
    nextAction: formData.nextAction.trim(),
    outcomeStatus: formData.outcomeStatus,
    decisionStatus: formData.decisionStatus,
    exceptionReason: formData.exceptionReason.trim(),
    desiredProfit: asNumber(formData.desiredProfit),
    buyingPrice: asNumber(formData.buyingPrice),
    saleEvidenceUrl: formData.saleEvidenceUrl.trim(),
    buyEvidenceUrl: formData.buyEvidenceUrl.trim(),
    fees: asNumber(formData.fees),
    shipping: asNumber(formData.shipping),
    supplies: asNumber(formData.supplies),
    notes: formData.notes.trim()
  });

  persistRows();
  render();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

decisionFilter.addEventListener("change", render);
searchInput.addEventListener("input", render);
runFreshPullButton.addEventListener("click", runFreshPull);
refreshDataButton.addEventListener("click", refreshLiveData);
exportCsvButton.addEventListener("click", exportCsv);
resetButton.addEventListener("click", resetRows);
if (itemForm) {
  itemForm.addEventListener("input", renderMarginPreview);
  itemForm.addEventListener("change", renderMarginPreview);
}

itemForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const formData = Object.fromEntries(new FormData(itemForm).entries());
  addRow(formData);
  itemForm.reset();
  renderMarginPreview();
});

window.addEventListener("storage", (event) => {
  if (event.key !== STORAGE_KEY) {
    return;
  }

  rows = loadRows();
  render();
});

persistRows();
const initialGeneratedAt = currentGeneratedAt();
if (initialGeneratedAt) {
  setLedgerActionMessage(`Live data loaded from research file generated ${formatDateTime(initialGeneratedAt)}.`);
} else if (!supportsFreshPull()) {
  setLedgerActionMessage("Run Fresh Pull is available when the app is opened through the local Sales OS server.");
}
render();
