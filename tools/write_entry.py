#!/usr/bin/env python3
"""Send an Info Analyzer OS JSON entry to the local SQLite server."""
import argparse, json, sys, urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("json_file", help="Path to entry JSON file, or '-' for stdin")
parser.add_argument("--url", default="http://127.0.0.1:8000/api/entries")
args = parser.parse_args()
raw = sys.stdin.read() if args.json_file == "-" else open(args.json_file, "r", encoding="utf-8").read()
payload = raw.encode("utf-8")
req = urllib.request.Request(args.url, data=payload, headers={"Content-Type":"application/json"}, method="POST")
with urllib.request.urlopen(req) as res:
    print(res.read().decode("utf-8"))
