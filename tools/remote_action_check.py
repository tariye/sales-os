#!/usr/bin/env python3
"""Run the ChatGPT Action API loop against a deployed HTTPS endpoint.

This wraps api_v1_loop_check.py but refuses localhost by default so the same
test can prove the external Action surface once the API is deployed.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--write-proof", default="")
    parser.add_argument("--allow-local", action="store_true")
    args = parser.parse_args()

    parsed = urlparse(args.base_url)
    local_hosts = {"127.0.0.1", "localhost", "0.0.0.0"}
    if not args.allow_local and (parsed.scheme != "https" or parsed.hostname in local_hosts):
        print("remote_action_check requires an HTTPS non-local base URL unless --allow-local is set.", file=sys.stderr)
        return 2

    script = Path(__file__).resolve().parent / "api_v1_loop_check.py"
    cmd = [
        sys.executable,
        str(script),
        "--base-url",
        args.base_url,
        "--api-key",
        args.api_key,
    ]
    if args.write_proof:
        cmd.extend(["--write-proof", args.write_proof])
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
