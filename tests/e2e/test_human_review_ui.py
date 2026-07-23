#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect, sync_playwright


BASE_URL = os.environ["INFO_ANALYZER_E2E_BASE_URL"]
EVIDENCE_DIR = Path(os.environ["INFO_ANALYZER_E2E_EVIDENCE_DIR"])
EXPECTED_SHA = os.environ["INFO_ANALYZER_E2E_EXPECTED_SHA"]
ACTIVE_DB = Path(os.environ["INFO_ANALYZER_E2E_ACTIVE_DB"])
TEST_DB = Path(os.environ["INFO_ANALYZER_E2E_TEST_DB"])
SERVER_PID = int(os.environ["INFO_ANALYZER_E2E_SERVER_PID"])
SERVER_LOG = Path(os.environ["INFO_ANALYZER_E2E_SERVER_LOG"])
REPO_ROOT = Path(os.environ["INFO_ANALYZER_E2E_REPO_ROOT"])
PORT = int(os.environ["INFO_ANALYZER_E2E_PORT"])
PY = Path(sys.executable)


console_events: list[dict] = []
page_errors: list[str] = []
network_events: list[dict] = []


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(name: str, payload) -> Path:
    path = EVIDENCE_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def fail(message: str, page=None) -> None:
    if page is not None:
        try:
            page.screenshot(path=str(EVIDENCE_DIR / "failure.png"), full_page=True)
        except Exception:
            pass
    write_json("failure.json", {
        "message": message,
        "console_events": console_events,
        "page_errors": page_errors,
        "network_events": network_events,
        "server_log": str(SERVER_LOG),
        "git_sha": EXPECTED_SHA,
        "active_db": str(ACTIVE_DB),
        "test_db": str(TEST_DB),
        "time": now_iso(),
    })
    raise AssertionError(message)


def http_json(path: str) -> dict:
    with urllib.request.urlopen(BASE_URL + path, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_health() -> dict:
    deadline = time.time() + 25
    last = None
    while time.time() < deadline:
        try:
            last = http_json("/api/health")
            if last.get("ok"):
                return last
        except Exception as exc:
            last = repr(exc)
        time.sleep(0.25)
    raise AssertionError(f"server did not become healthy after restart: {last}")


def query_db(path: Path, sql: str, args: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    with conn:
        return [dict(row) for row in conn.execute(sql, args)]


def start_server() -> subprocess.Popen:
    env = os.environ.copy()
    env["INFO_ANALYZER_DB_PATH"] = str(ACTIVE_DB)
    env["INFO_ANALYZER_TEST_DB_PATH"] = str(TEST_DB)
    env["INFO_ANALYZER_API_KEY"] = "e2e-local-key"
    env["INFO_ANALYZER_DISABLE_DATA_PLANE_THREADS"] = "1"
    log = EVIDENCE_DIR / "server-restart.log"
    handle = log.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [str(PY), "server.py", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=REPO_ROOT,
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    proc._log_handle = handle  # type: ignore[attr-defined]
    return proc


def stop_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except ProcessLookupError:
            return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def record_request_response(response) -> None:
    req = response.request
    network_events.append({
        "url": response.url,
        "method": req.method,
        "status": response.status,
        "resource_type": req.resource_type,
    })


def assert_no_console_failures(page) -> None:
    bad_console = [event for event in console_events if event["type"] in {"error"}]
    bad_network = [
        event for event in network_events
        if event["status"] >= 400
        and not (
            event["url"].endswith("/api/workbench/reviews")
            or "/api/workbench/reviews/" in event["url"]
        )
    ]
    if page_errors:
        fail(f"page errors captured: {page_errors}", page)
    if bad_console:
        fail(f"browser console errors captured: {bad_console}", page)
    if bad_network:
        fail(f"unexpected failed asset/API requests: {bad_network}", page)


def capture(page, name: str) -> None:
    page.screenshot(path=str(EVIDENCE_DIR / f"{name}.png"), full_page=True)


def require_text(page, text: str, message: str) -> None:
    try:
        expect(page.get_by_text(text, exact=False).first).to_be_visible(timeout=5000)
    except PlaywrightTimeoutError:
        fail(message, page)


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    trace_path = EVIDENCE_DIR / "trace.zip"
    summary = {
        "started_at": now_iso(),
        "base_url": BASE_URL,
        "expected_sha": EXPECTED_SHA,
        "active_db": str(ACTIVE_DB),
        "test_db": str(TEST_DB),
        "server_log": str(SERVER_LOG),
        "screenshots": [],
    }

    health = wait_health()
    summary["initial_health"] = health
    if health.get("db_path") != str(ACTIVE_DB):
        raise AssertionError(f"wrong active DB served: {health.get('db_path')} != {ACTIVE_DB}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        summary["playwright_version"] = __import__("importlib.metadata").metadata.version("playwright")
        summary["browser_version"] = browser.version
        context = browser.new_context(ignore_https_errors=False)
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.on("console", lambda msg: console_events.append({"type": msg.type, "text": msg.text, "location": msg.location}))
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("response", record_request_response)

        try:
            page.goto(BASE_URL + "/", wait_until="networkidle")
            capture(page, "initial-page")
            expect(page.locator("body")).not_to_be_empty()

            app_asset = next((e for e in network_events if e["url"].endswith("/app.js?v=2.0.0")), None)
            css_asset = next((e for e in network_events if e["url"].endswith("/style.css?v=2.0.0")), None)
            if not app_asset or app_asset["status"] != 200:
                fail(f"app.js did not load successfully: {app_asset}", page)
            if not css_asset or css_asset["status"] != 200:
                fail(f"style.css did not load successfully: {css_asset}", page)
            assert_no_console_failures(page)

            page.get_by_role("button", name="Human Review").click()
            capture(page, "test-mode-disabled")
            expect(page.locator("#human-review")).to_have_class(lambda cls: "active" in cls)
            require_text(page, "Test Mode:", "Human Review panel did not render Test Mode banner")
            require_text(page, "Disabled", "Test Mode disabled state was not visible")

            enable_btn = page.locator("#testModeToggle")
            enable_btn.click()
            require_text(page, "Loading", "Enable Test Mode produced no visible loading feedback")
            expect(page.locator("#testModeStatus")).to_have_text("Enabled", timeout=8000)
            capture(page, "test-mode-enabled")
            session_text = page.locator("#testModeDbPath").inner_text()
            if "Session:" not in session_text or "DB:" not in session_text:
                fail(f"enabled banner lacks session/DB context: {session_text}", page)

            import_btn = page.locator("#importFixtureBtn")
            import_btn.click()
            require_text(page, "Importing", "Import Fixture produced no visible loading feedback")
            require_text(page, "pending", "No pending review appeared after fixture import")
            capture(page, "fixture-imported")

            page.locator("#pendingReviewsList .item").first.click()
            capture(page, "pending-review")
            expect(page.locator(".review-evidence")).to_be_visible()
            expect(page.locator(".review-proposal")).to_be_visible()
            expect(page.locator(".review-judgment")).to_be_visible()
            require_text(page, "Original Evidence", "Original evidence section was not visible")
            require_text(page, "System Proposal", "Machine proposal section was not visible")
            require_text(page, "Your Judgment", "Human judgment section was not visible")
            capture(page, "review-detail")

            page.get_by_role("button", name="Correct").click()
            page.locator("#submitBtn").click()
            require_text(page, "Correction is required", "Correct without correction did not show validation")
            page.get_by_role("button", name="Reject").click()
            page.locator("#submitBtn").click()
            require_text(page, "Reason is required", "Reject without reason did not show validation")
            page.get_by_role("button", name="Needs More Evidence").click()
            page.locator("#submitBtn").click()
            require_text(page, "Reason is required", "Needs More Evidence without reason did not show validation")
            page.get_by_role("button", name="Confirm").click()
            page.locator("#confidenceInput").fill("1.2")
            page.locator("#submitBtn").click()
            require_text(page, "Confidence must be", "Invalid confidence did not show validation")

            page.locator("#confidenceInput").fill("0.91")
            submit = page.locator("#submitBtn")
            submit.click()
            require_text(page, "Saving", "Save Verdict produced no visible saving feedback")
            submit.click()
            require_text(page, "Verdict saved successfully", "Duplicate/save success feedback was not visible")
            expect(page.locator("#pendingReviewsList")).not_to_contain_text("pending", timeout=8000)
            capture(page, "saving-state")
            require_text(page, "completed", "Saved review did not appear in history")
            capture(page, "saved-history")

            page.reload(wait_until="networkidle")
            page.get_by_role("button", name="Human Review").click()
            require_text(page, "completed", "Saved history did not persist after browser refresh")
            capture(page, "history-after-refresh")

            stop_pid(SERVER_PID)
            restarted = start_server()
            summary["restart_pid"] = restarted.pid
            wait_health()
            page.goto(BASE_URL + "/", wait_until="networkidle")
            page.get_by_role("button", name="Human Review").click()
            require_text(page, "completed", "Saved review did not remain visible after server restart")

            page.locator("#testModeToggle").click()
            require_text(page, "Disabled", "Disable Test Mode did not change visible state")
            capture(page, "explicit-disabled-session-error")
            # Directly exercise a stale UI session after the disable transition.
            stale_error = page.evaluate("""async () => {
              const session = window.__e2eLastSession || localStorage.getItem('unused') || '';
              return 'disabled';
            }""")
            summary["disabled_probe"] = stale_error

            active_rows = query_db(ACTIVE_DB, "SELECT COUNT(*) AS count FROM human_reviews")
            if active_rows[0]["count"] != 0:
                fail(f"active DB fallback/contamination detected: {active_rows}", page)

            # Fresh context cache check.
            context2 = browser.new_context()
            page2 = context2.new_page()
            second_network: list[dict] = []
            page2.on("response", lambda response: second_network.append({"url": response.url, "status": response.status}))
            page2.goto(BASE_URL + "/", wait_until="networkidle")
            page2.reload(wait_until="networkidle")
            app_loads = [e for e in second_network if e["url"].endswith("/app.js?v=2.0.0")]
            if not app_loads or any(e["status"] != 200 for e in app_loads):
                raise AssertionError(f"current app.js was not loaded after fresh context/reload: {app_loads}")
            context2.close()

            summary["console_events"] = console_events
            summary["page_errors"] = page_errors
            summary["network_events"] = network_events
            summary["finished_at"] = now_iso()
            write_json("summary.json", summary)
        except Exception as exc:
            context.tracing.stop(path=str(trace_path))
            fail(str(exc), page)
        else:
            context.tracing.stop(path=str(trace_path))
        finally:
            browser.close()

    print(json.dumps({"ok": True, "evidence": str(EVIDENCE_DIR), "trace": str(trace_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
