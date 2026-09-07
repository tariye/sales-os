from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ServerHandle:
    proc: subprocess.Popen[str]
    port: int
    log_path: Path
    started: bool


def start_server(db_path: Path, api_key: str | None = "test-key") -> ServerHandle:
    log_dir = Path(tempfile.mkdtemp(prefix="info-analyzer-tests-"))
    log_path = log_dir / "server.log"
    env = os.environ.copy()
    env["INFO_ANALYZER_DB_PATH"] = str(db_path)
    env["PYTHONUNBUFFERED"] = "1"
    if api_key is None:
        env.pop("INFO_ANALYZER_API_KEY", None)
    else:
        env["INFO_ANALYZER_API_KEY"] = api_key
    for port in range(8150, 8180):
        log_file = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-u", "server.py", "--host", "127.0.0.1", "--port", str(port)],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.time() + 30
        started = False
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
                    if response.status == 200:
                        started = True
                        break
            except Exception:
                time.sleep(0.25)
        if started:
            log_file.close()
            return ServerHandle(proc=proc, port=port, log_path=log_path, started=started)
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        log_file.close()
    raise AssertionError(log_path.read_text(encoding="utf-8", errors="replace"))


def stop_server(handle: ServerHandle) -> None:
    if handle.proc.poll() is None:
        handle.proc.terminate()
        try:
            handle.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            handle.proc.kill()


def request_json(
    port: int,
    path: str,
    method: str = "GET",
    payload: Any | None = None,
    headers: dict[str, str] | None = None,
):
    url = f"http://127.0.0.1:{port}{path}"
    body = None
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
