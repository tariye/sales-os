#!/usr/bin/env python3
"""
Stock Pattern Recognition Engine.

Standalone first: this module can run without the web app and returns a
structured intelligence card for a ticker. The web app can then treat the
output as another source signal.
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sqlite3
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "info_analyzer.db"
SEC_USER_AGENT = "InfoAnalyzerOS/0.73 tariye@example.com"

COMMON_TICKERS = {
    "AAPL": {"cik": "0000320193", "name": "Apple Inc.", "yahoo": "AAPL"},
    "MSFT": {"cik": "0000789019", "name": "Microsoft Corporation", "yahoo": "MSFT"},
    "NVDA": {"cik": "0001045810", "name": "NVIDIA Corporation", "yahoo": "NVDA"},
    "AMZN": {"cik": "0001018724", "name": "Amazon.com, Inc.", "yahoo": "AMZN"},
    "GOOGL": {"cik": "0001652044", "name": "Alphabet Inc.", "yahoo": "GOOGL"},
    "META": {"cik": "0001326801", "name": "Meta Platforms, Inc.", "yahoo": "META"},
    "TSLA": {"cik": "0001318605", "name": "Tesla, Inc.", "yahoo": "TSLA"},
}

FOREIGN_TICKERS = {
    "SK HYNIX": {"name": "SK hynix Inc.", "yahoo": "000660.KS"},
    "000660": {"name": "SK hynix Inc.", "yahoo": "000660.KS"},
    "000660.KS": {"name": "SK hynix Inc.", "yahoo": "000660.KS"},
    "HXSCL": {"name": "SK hynix Inc.", "yahoo": "000660.KS"},
}

CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "long_term_debt_current": ["LongTermDebtCurrent"],
    "long_term_debt_noncurrent": ["LongTermDebtNoncurrent"],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def money(value) -> str:
    if value is None:
        return "n/a"
    try:
        n = float(value)
    except Exception:
        return "n/a"
    sign = "-" if n < 0 else ""
    n = abs(n)
    for suffix, denom in (("T", 1_000_000_000_000), ("B", 1_000_000_000), ("M", 1_000_000)):
        if n >= denom:
            return f"{sign}${n / denom:.2f}{suffix}"
    return f"{sign}${n:,.0f}"


def pct(value) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def safe_float(value):
    try:
        return float(value)
    except Exception:
        return None


def http_get(url: str, *, headers=None, timeout=20) -> bytes:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (ssl.SSLCertVerificationError, urllib.error.URLError) as exc:
        if isinstance(exc, urllib.error.URLError) and not isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError):
            raise
        # Local Python installs on this machine do not always have a valid CA
        # bundle. Retry only for public read-only market/document sources.
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            return resp.read()


def get_json(url: str, *, headers=None, timeout=20) -> dict:
    return json.loads(http_get(url, headers=headers, timeout=timeout).decode("utf-8"))


def normalize_symbol(symbol: str) -> str:
    return re.sub(r"\s+", " ", str(symbol or "").strip()).upper()


def resolve_symbol(symbol: str, company_hint: str = "") -> dict:
    raw = normalize_symbol(symbol)
    if raw in COMMON_TICKERS:
        return {"symbol": raw, **COMMON_TICKERS[raw], "sec_available": True}
    if raw in FOREIGN_TICKERS:
        info = FOREIGN_TICKERS[raw]
        return {"symbol": raw, "cik": "", **info, "sec_available": False}
    if "." in raw:
        return {"symbol": raw, "cik": "", "name": company_hint or raw, "yahoo": raw, "sec_available": False}
    try:
        data = get_json("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": SEC_USER_AGENT})
        for row in data.values():
            if row.get("ticker", "").upper() == raw:
                cik = str(row.get("cik_str", "")).zfill(10)
                return {
                    "symbol": raw,
                    "cik": cik,
                    "name": row.get("title") or company_hint or raw,
                    "yahoo": raw,
                    "sec_available": True,
                }
    except Exception:
        pass
    return {"symbol": raw, "cik": "", "name": company_hint or raw, "yahoo": raw, "sec_available": False}


def fetch_quote(yahoo_symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(yahoo_symbol)}?range=1y&interval=1d"
    data = get_json(url, headers={"User-Agent": "Mozilla/5.0"})
    result = (data.get("chart", {}).get("result") or [{}])[0]
    meta = result.get("meta") or {}
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes = [safe_float(x) for x in quote.get("close", []) if x is not None]
    closes = [x for x in closes if x is not None]
    current = safe_float(meta.get("regularMarketPrice"))
    previous = safe_float(meta.get("chartPreviousClose"))
    year_high = max(closes) if closes else safe_float(meta.get("fiftyTwoWeekHigh"))
    year_low = min(closes) if closes else safe_float(meta.get("fiftyTwoWeekLow"))
    one_year_return = ((current - closes[0]) / closes[0]) if current is not None and closes else None
    return {
        "source": "Yahoo Finance chart API",
        "symbol": yahoo_symbol,
        "currency": meta.get("currency"),
        "exchange": meta.get("exchangeName") or meta.get("fullExchangeName"),
        "price": current,
        "previous_close": previous,
        "one_year_high": year_high,
        "one_year_low": year_low,
        "one_year_return": one_year_return,
        "source_url": url,
    }


def fetch_news(yahoo_symbol: str, limit: int = 8) -> list[dict]:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.parse.quote(yahoo_symbol)}&region=US&lang=en-US"
    raw = http_get(url, headers={"User-Agent": "Mozilla/5.0"})
    root = ET.fromstring(raw)
    items = []
    for item in root.findall("./channel/item")[:limit]:
        items.append({
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "published": (item.findtext("pubDate") or "").strip(),
        })
    return items


def fetch_sec_facts(cik: str) -> dict:
    if not cik:
        return {}
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json"
    data = get_json(url, headers={"User-Agent": SEC_USER_AGENT})
    data["_source_url"] = url
    return data


def concept_units(companyfacts: dict, names: list[str]) -> list[dict]:
    facts = companyfacts.get("facts", {}).get("us-gaap", {})
    for name in names:
        units = facts.get(name, {}).get("units", {})
        if "USD" in units:
            return units["USD"]
        if "USD/shares" in units:
            return units["USD/shares"]
    return []


def period_score(item: dict) -> tuple:
    return (item.get("filed") or "", item.get("end") or "", item.get("fy") or 0)


def latest_item(items: list[dict], *, form=None, fp=None) -> dict | None:
    filtered = []
    for item in items:
        if form and item.get("form") not in form:
            continue
        if fp and item.get("fp") not in fp:
            continue
        if item.get("val") is None:
            continue
        filtered.append(item)
    if not filtered:
        return None
    return sorted(filtered, key=period_score, reverse=True)[0]


def duration_days(item: dict) -> int | None:
    try:
        start = item.get("start")
        end = item.get("end")
        if not start or not end:
            return None
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
        return (e - s).days
    except Exception:
        return None


def latest_quarter_item(items: list[dict]) -> dict | None:
    candidates = [
        item for item in items
        if item.get("val") is not None
        and item.get("form") == "10-Q"
        and item.get("fp") in {"Q1", "Q2", "Q3"}
    ]
    true_quarters = []
    for item in candidates:
        frame = str(item.get("frame") or "")
        days = duration_days(item)
        if re.fullmatch(r"CY\d{4}Q[1-4]", frame) or (days is not None and 75 <= days <= 110):
            true_quarters.append(item)
    if true_quarters:
        return sorted(true_quarters, key=period_score, reverse=True)[0]
    return sorted(candidates, key=period_score, reverse=True)[0] if candidates else None


def prior_period_item(items: list[dict], current: dict | None) -> dict | None:
    if not current:
        return None
    current_days = duration_days(current)
    candidates = [
        item for item in items
        if item.get("val") is not None
        and item.get("form") == current.get("form")
        and item.get("fp") == current.get("fp")
        and item.get("fy") == (current.get("fy") or 0) - 1
    ]
    if current_days is not None:
        comparable = [
            item for item in candidates
            if duration_days(item) is not None and abs(duration_days(item) - current_days) <= 20
        ]
        if comparable:
            candidates = comparable
    if not candidates:
        candidates = [
            item for item in items
            if item.get("val") is not None
            and item.get("end", "") < current.get("end", "")
            and item.get("form") == current.get("form")
        ]
        if current_days is not None:
            comparable = [
                item for item in candidates
                if duration_days(item) is not None and abs(duration_days(item) - current_days) <= 20
            ]
            if comparable:
                candidates = comparable
    return sorted(candidates, key=period_score, reverse=True)[0] if candidates else None


def extract_financials(companyfacts: dict) -> dict:
    if not companyfacts:
        return {"available": False, "reason": "SEC company facts unavailable for this ticker."}
    out = {"available": True, "source": "SEC companyfacts", "source_url": companyfacts.get("_source_url")}
    quarterly = {}
    annual = {}
    comparisons = {}
    for key, concepts in CONCEPTS.items():
        items = concept_units(companyfacts, concepts)
        q = latest_quarter_item(items)
        y = latest_item(items, form={"10-K"}, fp={"FY"})
        quarterly[key] = q
        annual[key] = y
        prior_q = prior_period_item(items, q)
        prior_y = prior_period_item(items, y)
        comparisons[key] = {
            "quarter_yoy": growth(q, prior_q),
            "annual_yoy": growth(y, prior_y),
        }
    out["latest_quarter"] = simplify_periods(quarterly)
    out["latest_annual"] = simplify_periods(annual)
    out["comparisons"] = comparisons
    out["derived"] = derived_metrics(out["latest_quarter"], out["latest_annual"])
    return out


def growth(current: dict | None, prior: dict | None):
    c = safe_float(current.get("val")) if current else None
    p = safe_float(prior.get("val")) if prior else None
    if c is None or p in (None, 0):
        return None
    return (c - p) / abs(p)


def simplify_periods(periods: dict) -> dict:
    out = {}
    for key, item in periods.items():
        if not item:
            out[key] = None
            continue
        out[key] = {
            "value": item.get("val"),
            "display": money(item.get("val")),
            "form": item.get("form"),
            "fy": item.get("fy"),
            "fp": item.get("fp"),
            "start": item.get("start"),
            "end": item.get("end"),
            "filed": item.get("filed"),
            "frame": item.get("frame"),
        }
    return out


def val(periods: dict, key: str):
    item = periods.get(key) or {}
    return safe_float(item.get("value"))


def derived_metrics(q: dict, y: dict) -> dict:
    def margins(period):
        revenue = val(period, "revenue")
        gross_profit = val(period, "gross_profit")
        operating_income = val(period, "operating_income")
        net_income = val(period, "net_income")
        cfo = val(period, "operating_cash_flow")
        capex = val(period, "capex")
        return {
            "gross_margin": gross_profit / revenue if revenue else None,
            "operating_margin": operating_income / revenue if revenue else None,
            "net_margin": net_income / revenue if revenue else None,
            "free_cash_flow": (cfo - abs(capex)) if cfo is not None and capex is not None else None,
        }
    return {
        "latest_quarter": margins(q),
        "latest_annual": margins(y),
        "debt_estimate": sum(x or 0 for x in [val(q, "long_term_debt_current"), val(q, "long_term_debt_noncurrent")]) or None,
    }


def load_memory_context(symbol: str, company: str, limit: int = 8, db_path: Path = DB_PATH) -> list[dict]:
    if not db_path.exists():
        return []
    terms = [symbol, company]
    query = " OR ".join(["title LIKE ? OR entity LIKE ? OR raw_input LIKE ? OR signal LIKE ? OR interpretation LIKE ?"] * len(terms))
    params = []
    for term in terms:
        like = f"%{term}%"
        params.extend([like, like, like, like, like])
    if not query:
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT id, title, domain, entity, signal, interpretation, returned_action, tracking_metric, updated_at
            FROM entries
            WHERE status NOT IN ('archived','superseded') AND ({query})
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def build_signals(symbol_info: dict, quote: dict, financials: dict, news: list[dict], memory: list[dict]) -> list[dict]:
    signals = []
    q = financials.get("latest_quarter", {})
    y = financials.get("latest_annual", {})
    derived = financials.get("derived", {})
    comparisons = financials.get("comparisons", {})
    revenue_q = q.get("revenue") or {}
    net_q = q.get("net_income") or {}
    revenue_growth = (comparisons.get("revenue") or {}).get("quarter_yoy")
    net_growth = (comparisons.get("net_income") or {}).get("quarter_yoy")
    gross_margin = (derived.get("latest_quarter") or {}).get("gross_margin")
    fcf = (derived.get("latest_annual") or {}).get("free_cash_flow")
    if revenue_q:
        signals.append({
            "type": "demand",
            "signal": f"Latest reported quarter revenue: {revenue_q.get('display')} through {revenue_q.get('end')}.",
            "track": "Revenue growth, segment growth, guidance, demand commentary.",
            "direction": "bullish" if revenue_growth and revenue_growth > 0 else "watch",
        })
    if gross_margin is not None:
        signals.append({
            "type": "profit",
            "signal": f"Latest reported gross margin: {pct(gross_margin)}.",
            "track": "Gross margin trend versus prior quarter and prior year.",
            "direction": "bullish" if gross_margin >= 0.35 else "watch",
        })
    if net_q:
        signals.append({
            "type": "earnings",
            "signal": f"Latest reported quarter net income: {net_q.get('display')}; YoY growth: {pct(net_growth)}.",
            "track": "Net income growth versus operating income and cash conversion.",
            "direction": "bullish" if net_growth and net_growth > 0 else "watch",
        })
    if fcf is not None:
        signals.append({
            "type": "cash",
            "signal": f"Latest reported annual free cash flow estimate: {money(fcf)}.",
            "track": "Operating cash flow minus capex, buybacks, debt, and cash balance.",
            "direction": "bullish" if fcf > 0 else "risk",
        })
    if quote.get("one_year_return") is not None:
        signals.append({
            "type": "market",
            "signal": f"One-year price move: {pct(quote.get('one_year_return'))}.",
            "track": "Price versus fundamentals; avoid confusing momentum with business quality.",
            "direction": "watch",
        })
    if news:
        signals.append({
            "type": "news",
            "signal": f"{len(news)} fresh headline(s) pulled for current context.",
            "track": "Whether headlines change revenue, margin, capital allocation, regulation, or valuation thesis.",
            "direction": "watch",
        })
    if memory:
        signals.append({
            "type": "memory",
            "signal": f"{len(memory)} local memory record(s) matched this company.",
            "track": "Prior thesis, older questions, actions, and contradiction signals.",
            "direction": "context",
        })
    return signals


def decision_frame(symbol_info: dict, financials: dict, signals: list[dict], news: list[dict]) -> dict:
    risk_count = sum(1 for s in signals if s.get("direction") == "risk")
    bullish_count = sum(1 for s in signals if s.get("direction") == "bullish")
    missing_financials = not financials.get("available")
    if missing_financials:
        action = "research deeper"
        reason = "No SEC companyfacts were available, so current news and market data need source validation before underwriting."
    elif risk_count:
        action = "watch"
        reason = "One or more risk signals require confirmation before capital allocation."
    elif bullish_count >= 3:
        action = "research buy setup"
        reason = "Demand, margin, and cash signals look strong enough to underwrite valuation and downside."
    else:
        action = "watch"
        reason = "The signal set is incomplete or mixed; define the next confirming metric before action."
    return {
        "action": action,
        "reason": reason,
        "not_investment_advice": True,
        "next_step": f"Read the latest filing/news for {symbol_info['name']} and compare price to revenue growth, margin, free cash flow, and thesis risk.",
        "tracking_metric": "Revenue growth, gross margin, operating margin, free cash flow, net cash/debt, guidance, headline catalyst, valuation multiple.",
        "resurfacing_trigger": f"Resurface when {symbol_info['symbol']}, {symbol_info['name']}, earnings, guidance, margin, cash flow, or major headline appears.",
    }


def analyze_stock(symbol: str, company_hint: str = "", include_news: bool = True, include_memory: bool = True) -> dict:
    info = resolve_symbol(symbol, company_hint)
    errors = []
    quote = {}
    news = []
    companyfacts = {}
    try:
        quote = fetch_quote(info["yahoo"])
    except Exception as exc:
        errors.append(f"quote: {exc}")
    if include_news:
        try:
            news = fetch_news(info["yahoo"])
        except Exception as exc:
            errors.append(f"news: {exc}")
    if info.get("sec_available"):
        try:
            companyfacts = fetch_sec_facts(info["cik"])
        except Exception as exc:
            errors.append(f"sec: {exc}")
    financials = extract_financials(companyfacts)
    memory = load_memory_context(info["symbol"], info["name"]) if include_memory else []
    signals = build_signals(info, quote, financials, news, memory)
    decision = decision_frame(info, financials, signals, news)
    return {
        "generated_at": now_iso(),
        "engine": "stock-pattern-recognition-v0.1",
        "company": info,
        "quote": quote,
        "financials": financials,
        "news": news,
        "memory_context": memory,
        "signals": signals,
        "decision_frame": decision,
        "source_links": {
            "sec_companyfacts": financials.get("source_url"),
            "yahoo_chart": quote.get("source_url"),
            "yahoo_news": f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.parse.quote(info['yahoo'])}&region=US&lang=en-US",
        },
        "errors": errors,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run stock pattern recognition engine")
    parser.add_argument("symbol")
    parser.add_argument("--company", default="")
    parser.add_argument("--no-news", action="store_true")
    parser.add_argument("--no-memory", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(
        analyze_stock(args.symbol, args.company, include_news=not args.no_news, include_memory=not args.no_memory),
        indent=2,
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
