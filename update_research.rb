#!/usr/bin/env ruby
# frozen_string_literal: true

require "json"
require "fileutils"
require "open3"
require "cgi"
require "time"

PROJECT_ROOT = File.expand_path("..", __dir__)
DATA_DIR = File.join(PROJECT_ROOT, "data")
WATCHLIST_PATH = File.join(DATA_DIR, "watchlist.json")
DISCOVERY_SEEDS_PATH = File.join(DATA_DIR, "discovery-seeds.json")
LIVE_DATA_JSON_PATH = File.join(DATA_DIR, "live-data.json")
LIVE_DATA_JS_PATH = File.join(DATA_DIR, "live-data.js")
MAX_SNAPSHOTS = 120
DAY_RANGE = 30
TIMEZONE = "America/Los_Angeles"
RESEARCH_URL = "https://www.ebay.com/sh/research?marketplace=EBAY-US&tabName=SOLD"
DISCOVERY_RESULT_LIMIT = 40

def shell_escape(text)
  "'" + text.to_s.gsub("'", %q('"'"')) + "'"
end

def applescript_string(text)
  text.to_json
end

def run_applescript(script)
  stdout, stderr, status = Open3.capture3("osascript", stdin_data: script)
  raise "AppleScript failed: #{stderr.strip}" unless status.success?

  stdout.strip
end

def ensure_research_tab!
  script = <<~APPLESCRIPT
    tell application "Google Chrome"
      if (count of windows) = 0 then make new window
      set foundTab to false
      repeat with wi from 1 to count of windows
        set w to window wi
        repeat with ti from 1 to count of tabs of w
          set t to tab ti of w
          if (URL of t contains "www.ebay.com/sh/research") then
            set active tab index of w to ti
            set index of w to 1
            activate
            set foundTab to true
            exit repeat
          end if
        end repeat
        if foundTab then exit repeat
      end repeat
      if foundTab is false then
        set newTab to make new tab at end of tabs of front window with properties {URL:#{applescript_string(RESEARCH_URL)}}
        set active tab index of front window to (count of tabs of front window)
        activate
      end if
    end tell
  APPLESCRIPT

  run_applescript(script)
  sleep 2
end

def execute_in_research_tab(js_code)
  script = <<~APPLESCRIPT
    tell application "Google Chrome"
      repeat with wi from 1 to count of windows
        set w to window wi
        repeat with ti from 1 to count of tabs of w
          set t to tab ti of w
          if (URL of t contains "www.ebay.com/sh/research") then
            set active tab index of w to ti
            set index of w to 1
            activate
            return execute active tab of w javascript #{applescript_string(js_code)}
          end if
        end repeat
      end repeat
    end tell
  APPLESCRIPT

  run_applescript(script)
end

def to_epoch_ms(time)
  (time.to_f * 1000).to_i
end

def parse_money(text)
  text.to_s.gsub(/[^\d.\-]/, "").to_f
end

def parse_percent(text)
  text.to_s.gsub(/[^\d.\-]/, "").to_f
end

def parse_integer(text)
  text.to_s.gsub(/[^\d\-]/, "").to_i
end

def load_watchlist
  JSON.parse(File.read(WATCHLIST_PATH))
end

def load_discovery_seeds
  JSON.parse(File.read(DISCOVERY_SEEDS_PATH))
end

def load_existing_live_data
  return { "snapshots" => [] } unless File.exist?(LIVE_DATA_JSON_PATH)

  JSON.parse(File.read(LIVE_DATA_JSON_PATH))
rescue JSON::ParserError
  { "snapshots" => [] }
end

def build_sale_evidence_url(query, category_id, start_ms, end_ms)
  "https://www.ebay.com/sh/research?marketplace=EBAY-US&keywords=#{CGI.escape(query).gsub('+', '+')}&dayRange=#{DAY_RANGE}&endDate=#{end_ms}&startDate=#{start_ms}&categoryId=#{category_id}&tabName=SOLD&tz=#{CGI.escape(TIMEZONE)}"
end

def build_request_url(query, category_id, start_ms, end_ms)
  "/sh/research/api/search?marketplace=EBAY-US&keywords=#{CGI.escape(query).gsub('+', '+')}&dayRange=#{DAY_RANGE}&endDate=#{end_ms}&startDate=#{start_ms}&categoryId=#{category_id}&tabName=SOLD&tz=#{CGI.escape(TIMEZONE)}&modules=aggregates&modules=resultsHeader"
end

def build_search_results_url(query, category_id, start_ms, end_ms, limit)
  "/sh/research/api/search?marketplace=EBAY-US&keywords=#{CGI.escape(query).gsub('+', '+')}&dayRange=#{DAY_RANGE}&endDate=#{end_ms}&startDate=#{start_ms}&categoryId=#{category_id}&offset=0&limit=#{limit}&tabName=SOLD&tz=#{CGI.escape(TIMEZONE)}&modules=searchResults"
end

def fetch_aggregates(query:, category_id:, start_ms:, end_ms:)
  url = build_request_url(query, category_id, start_ms, end_ms)
  js_code = <<~JAVASCRIPT
    (() => {
      var xhr = new XMLHttpRequest();
      xhr.open("GET", #{url.to_json}, false);
      xhr.send(null);
      return xhr.responseText;
    })()
  JAVASCRIPT

  response_text = execute_in_research_tab(js_code)
  parts = parse_json_lines(response_text, query)
  aggregate = parts.find { |part| part["_type"] == "ResearchAggregateModule" }
  raise "No aggregate data returned for #{query}" unless aggregate

  metrics = {}
  aggregate.fetch("sections", []).each do |section|
    section.fetch("dataItems", []).each do |item|
      metrics[item.dig("header", "accessibilityText")] = item.dig("value", "accessibilityText")
    end
  end
  metrics
end

def fetch_search_results(query:, category_id:, start_ms:, end_ms:, limit:)
  url = build_search_results_url(query, category_id, start_ms, end_ms, limit)
  js_code = <<~JAVASCRIPT
    (() => {
      var xhr = new XMLHttpRequest();
      xhr.open("GET", #{url.to_json}, false);
      xhr.send(null);
      return xhr.responseText;
    })()
  JAVASCRIPT

  response_text = execute_in_research_tab(js_code)
  parts = parse_json_lines(response_text, query)
  results_module = parts.find { |part| part["_type"] == "SearchResultsModule" }
  raise "No search results returned for #{query}" unless results_module

  results_module.fetch("results", [])
end

def parse_json_lines(response_text, context)
  response_text
    .encode("UTF-8", invalid: :replace, undef: :replace, replace: "")
    .split(/\n+/)
    .map(&:strip)
    .reject(&:empty?)
    .each_with_object([]) do |line, parsed_lines|
      next unless line.start_with?("{", "[")

      begin
        parsed_lines << JSON.parse(line)
      rescue JSON::ParserError => e
        warn "Skipping malformed Seller Hub response line for #{context}: #{e.message}"
      end
    end
end

def ledger_row_for(item, metrics, timestamp, start_ms, end_ms)
  {
    "id" => item.fetch("id"),
    "item" => item.fetch("item"),
    "category" => item.fetch("category"),
    "route" => item.fetch("route"),
    "researchDate" => timestamp.strftime("%Y-%m-%d"),
    "researchWindow" => "Last 30 Days",
    "avgSalePrice" => parse_money(metrics["Avg sold price"]),
    "salesVolume" => parse_integer(metrics["Total sold"]),
    "sellThrough" => parse_percent(metrics["Sell-through"]),
    "totalSellers" => parse_integer(metrics["Total sellers"]),
    "buyingPrice" => item.fetch("buyingPrice"),
    "fees" => item.fetch("fees"),
    "shipping" => item.fetch("shipping"),
    "supplies" => item.fetch("supplies"),
    "saleEvidenceUrl" => build_sale_evidence_url(item.fetch("query"), item.fetch("categoryId"), start_ms, end_ms),
    "buyEvidenceUrl" => item.fetch("buyEvidenceUrl"),
    "notes" => "Auto-ingested Seller Hub data. #{item.fetch('notes')}"
  }
end

def merge_snapshots(existing_snapshots, new_snapshot)
  snapshots = existing_snapshots.dup
  snapshots << new_snapshot
  snapshots.uniq { |snapshot| snapshot["capturedAt"] }.last(MAX_SNAPSHOTS)
end

def text_from_display(display)
  return "" unless display

  if display.is_a?(Hash)
    if display["textSpans"].is_a?(Array)
      return display["textSpans"].map { |span| span["text"] }.join(" ").strip
    end
    return display["accessibilityText"].to_s if display["accessibilityText"]
    return display["value"].to_s if display["value"]
  end

  display.to_s
end

def normalize_product_name(title, patterns)
  patterns.each do |pattern_text|
    pattern = Regexp.new(pattern_text, Regexp::IGNORECASE)
    match = title.match(pattern)
    next unless match

    return canonicalize_product_name(match[0])
  end
  nil
end

def canonicalize_product_name(name)
  normalized = name.to_s.strip.gsub(/\s+/, " ")
  normalized = normalized.gsub(/\bpro max\b/i, "Pro Max")
  normalized = normalized.gsub(/\bpro\b/i, "Pro")
  normalized = normalized.gsub(/\bplus\b/i, "Plus")
  normalized = normalized.gsub(/\bmini\b/i, "Mini")
  normalized = normalized.gsub(/\bslim\b/i, "Slim")
  normalized = normalized.gsub(/\bultra\b/i, "Ultra")
  normalized = normalized.gsub(/\bfe\b/i, "FE")
  normalized = normalized.gsub(/\bm(\d)\b/i, 'M\1')
  normalized = normalized.gsub(/\bps5\b/i, "PS5")
  normalized = normalized.gsub(/\biphone\b/i, "iPhone")
  normalized = normalized.gsub(/\bipad\b/i, "iPad")
  normalized = normalized.gsub(/\bmacbook\b/i, "MacBook")
  normalized = normalized.gsub(/\bgalaxy\b/i, "Galaxy")
  normalized = normalized.gsub(/\bxbox\b/i, "Xbox")
  normalized = normalized.gsub(/\bnintendo\b/i, "Nintendo")
  normalized.strip
end

def parse_search_result(result, seed)
  title = text_from_display(result.dig("listing", "title"))
  items_sold = parse_integer(text_from_display(result["itemssold"]))
  avg_sale_price = parse_money(text_from_display(result.dig("avgsalesprice", "avgsalesprice")))
  last_sold = text_from_display(result["datelastsold"])
  product_name = normalize_product_name(title, seed.fetch("patterns"))
  return nil if product_name.nil? || items_sold <= 0

  {
    "product" => product_name,
    "seedQuery" => seed.fetch("query"),
    "category" => seed.fetch("category"),
    "title" => title,
    "salesVolume" => items_sold,
    "avgSalePrice" => avg_sale_price,
    "lastSold" => last_sold
  }
end

def discovery_products_for_seed(seed, start_ms, end_ms)
  results = fetch_search_results(
    query: seed.fetch("query"),
    category_id: seed.fetch("categoryId"),
    start_ms: start_ms,
    end_ms: end_ms,
    limit: DISCOVERY_RESULT_LIMIT
  )

  aggregate_map = {}
  results.each do |result|
    parsed = parse_search_result(result, seed)
    next unless parsed

    product = parsed.fetch("product")
    aggregate_map[product] ||= {
      "id" => product.downcase.gsub(/[^a-z0-9]+/, "-").gsub(/^-|-$/, ""),
      "item" => product,
      "category" => parsed.fetch("category"),
      "route" => "Discovery",
      "seedQuery" => parsed.fetch("seedQuery"),
      "salesVolume" => 0,
      "weightedSalesValue" => 0.0,
      "sampleTitles" => [],
      "lastSold" => parsed.fetch("lastSold")
    }

    entry = aggregate_map[product]
    entry["salesVolume"] += parsed.fetch("salesVolume")
    entry["weightedSalesValue"] += parsed.fetch("avgSalePrice") * parsed.fetch("salesVolume")
    entry["sampleTitles"] << parsed.fetch("title") if entry["sampleTitles"].length < 3
    entry["lastSold"] = parsed.fetch("lastSold") unless parsed.fetch("lastSold").empty?
  end

  aggregate_map.values.map do |entry|
    avg_sale = entry["salesVolume"] > 0 ? (entry["weightedSalesValue"] / entry["salesVolume"]).round(2) : 0.0
    {
      "id" => entry.fetch("id"),
      "item" => entry.fetch("item"),
      "category" => entry.fetch("category"),
      "route" => "Discovery",
      "seedQuery" => entry.fetch("seedQuery"),
      "currentVolume" => entry.fetch("salesVolume"),
      "avgSalePrice" => avg_sale,
      "sampleTitles" => entry.fetch("sampleTitles"),
      "lastSold" => entry.fetch("lastSold")
    }
  end
end

def merge_discovery_products(discovery_seeds, start_ms, end_ms)
  combined = {}

  discovery_seeds.each do |seed|
    seed_entries = discovery_products_for_seed(seed, start_ms, end_ms)
  rescue StandardError => e
    warn "Skipping discovery seed #{seed.fetch('id', seed.fetch('query', 'unknown'))}: #{e.message}"
    next
  else
    seed_entries.each do |entry|
      combined[entry.fetch("id")] ||= {
        "id" => entry.fetch("id"),
        "item" => entry.fetch("item"),
        "category" => entry.fetch("category"),
        "route" => "Discovery",
        "seedQueries" => [],
        "currentVolume" => 0,
        "weightedSalesValue" => 0.0,
        "sampleTitles" => [],
        "lastSold" => entry.fetch("lastSold")
      }

      combined_entry = combined[entry.fetch("id")]
      combined_entry["seedQueries"] |= [entry.fetch("seedQuery")]
      combined_entry["currentVolume"] += entry.fetch("currentVolume")
      combined_entry["weightedSalesValue"] += entry.fetch("avgSalePrice") * entry.fetch("currentVolume")
      combined_entry["sampleTitles"] |= entry.fetch("sampleTitles")
      combined_entry["lastSold"] = entry.fetch("lastSold") unless entry.fetch("lastSold").empty?
    end
  end

  combined.values.map do |entry|
    avg_sale = entry["currentVolume"] > 0 ? (entry["weightedSalesValue"] / entry["currentVolume"]).round(2) : 0.0
    {
      "id" => entry.fetch("id"),
      "item" => entry.fetch("item"),
      "category" => entry.fetch("category"),
      "route" => "Discovery",
      "seedQueries" => entry.fetch("seedQueries"),
      "currentVolume" => entry.fetch("currentVolume"),
      "avgSalePrice" => avg_sale,
      "sampleTitles" => entry.fetch("sampleTitles").first(3),
      "lastSold" => entry.fetch("lastSold")
    }
  end.sort_by { |entry| [-entry.fetch("currentVolume"), entry.fetch("item")] }.first(40)
end

def discovery_snapshot_from_products(products, captured_at)
  {
    "capturedAt" => captured_at,
    "items" => products.map do |product|
      {
        "id" => product.fetch("id"),
        "item" => product.fetch("item"),
        "category" => product.fetch("category"),
        "route" => "Discovery",
        "salesVolume" => product.fetch("currentVolume"),
        "avgSalePrice" => product.fetch("avgSalePrice")
      }
    end
  }
end

def write_live_data(live_data)
  FileUtils.mkdir_p(DATA_DIR)
  File.write(LIVE_DATA_JSON_PATH, JSON.pretty_generate(live_data) + "\n")
  File.write(LIVE_DATA_JS_PATH, "window.SALES_OS_LIVE_DATA = #{JSON.generate(live_data)};\n")
end

timestamp = Time.now
start_time = timestamp - (DAY_RANGE * 24 * 60 * 60)
start_ms = to_epoch_ms(start_time)
end_ms = to_epoch_ms(timestamp)

ensure_research_tab!

watchlist = load_watchlist
discovery_seeds = load_discovery_seeds
ledger_rows = watchlist.map do |item|
  metrics = fetch_aggregates(
    query: item.fetch("query"),
    category_id: item.fetch("categoryId"),
    start_ms: start_ms,
    end_ms: end_ms
  )
  ledger_row_for(item, metrics, timestamp, start_ms, end_ms)
end

discovery_products = merge_discovery_products(discovery_seeds, start_ms, end_ms)

snapshot = {
  "capturedAt" => timestamp.iso8601,
  "items" => ledger_rows.map do |row|
    {
      "id" => row.fetch("id"),
      "item" => row.fetch("item"),
      "category" => row.fetch("category"),
      "route" => row.fetch("route"),
      "salesVolume" => row.fetch("salesVolume"),
      "sellThrough" => row.fetch("sellThrough")
    }
  end
}

discovery_snapshot = discovery_snapshot_from_products(discovery_products, timestamp.iso8601)

existing_live_data = load_existing_live_data
live_data = {
  "generatedAt" => timestamp.iso8601,
  "source" => "eBay Seller Hub Product Research",
  "ledgerRows" => ledger_rows,
  "snapshots" => merge_snapshots(existing_live_data.fetch("snapshots", []), snapshot),
  "discoveryProducts" => discovery_products,
  "discoverySnapshots" => merge_snapshots(existing_live_data.fetch("discoverySnapshots", []), discovery_snapshot)
}

write_live_data(live_data)

puts "Updated #{LIVE_DATA_JSON_PATH}"
puts "Generated at: #{live_data.fetch('generatedAt')}"
puts "Rows: #{ledger_rows.length}"
