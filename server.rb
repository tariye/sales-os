#!/usr/bin/env ruby
# frozen_string_literal: true

require "json"
require "open3"
require "thread"
require "time"
require "webrick"

PROJECT_ROOT = __dir__
LIVE_DATA_JSON_PATH = File.join(PROJECT_ROOT, "data", "live-data.json")
UPDATE_SCRIPT_PATH = File.join(PROJECT_ROOT, "scripts", "update_research.rb")
PORT = Integer(ENV.fetch("SALES_OS_PORT", "4173"))

refresh_lock = Mutex.new
refresh_running = false

def json_response(response, status:, body:)
  response.status = status
  response["Content-Type"] = "application/json"
  response.body = JSON.generate(body)
end

def live_data_summary
  return {} unless File.exist?(LIVE_DATA_JSON_PATH)

  JSON.parse(File.read(LIVE_DATA_JSON_PATH))
rescue JSON::ParserError
  {}
end

server = WEBrick::HTTPServer.new(
  Port: PORT,
  DocumentRoot: PROJECT_ROOT,
  AccessLog: [],
  Logger: WEBrick::Log.new($stderr, WEBrick::Log::WARN)
)

server.mount_proc "/api/status" do |_request, response|
  live_data = live_data_summary
  json_response(
    response,
    status: 200,
    body: {
      ok: true,
      generatedAt: live_data["generatedAt"],
      source: live_data["source"],
      rows: Array(live_data["ledgerRows"]).length,
      discoveryProducts: Array(live_data["discoveryProducts"]).length
    }
  )
end

server.mount_proc "/api/run-refresh" do |request, response|
  unless request.request_method == "POST"
    json_response(response, status: 405, body: { ok: false, error: "Use POST." })
    next
  end

  lock_acquired = refresh_lock.try_lock
  unless lock_acquired
    json_response(response, status: 409, body: { ok: false, error: "A refresh is already running." })
    next
  end

  begin
    if refresh_running
      json_response(response, status: 409, body: { ok: false, error: "A refresh is already running." })
      next
    end

    refresh_running = true
    started_at = Time.now
    stdout, stderr, status = Open3.capture3("ruby", UPDATE_SCRIPT_PATH, chdir: PROJECT_ROOT)
    finished_at = Time.now

    if status.success?
      live_data = live_data_summary
      json_response(
        response,
        status: 200,
        body: {
          ok: true,
          generatedAt: live_data["generatedAt"],
          source: live_data["source"],
          durationSeconds: (finished_at - started_at).round(1),
          output: stdout.strip
        }
      )
    else
      json_response(
        response,
        status: 500,
        body: {
          ok: false,
          error: "Research refresh failed.",
          durationSeconds: (finished_at - started_at).round(1),
          output: stdout.strip,
          details: stderr.strip
        }
      )
    end
  ensure
    refresh_running = false
    refresh_lock.unlock
  end
end

trap("INT") { server.shutdown }
trap("TERM") { server.shutdown }

server.start
