#!/usr/bin/env python3
"""
Info Analyzer Computational Layer — Local Processing Daemon

Runs as a background process that:
1. Polls the queue for pending entries
2. Enriches each with Claude reasoning (signal → lesson)
3. Detects patterns across domains
4. Writes results back to the site

Usage:
    python3 processor.py
    python3 processor.py --interval 30 --batch-size 5

Exits on Ctrl+C.
"""

import urllib.request
import urllib.error
import json
import time
import sys
import argparse
from datetime import datetime
from typing import Optional


class Processor:
    def __init__(self, base_url: str = "http://127.0.0.1:8000/api", interval: int = 60, batch_size: int = 10):
        self.base_url = base_url
        self.interval = interval
        self.batch_size = batch_size
        self.processed_count = 0
        self.pattern_count = 0

    def log(self, msg: str, level: str = "INFO"):
        """Print timestamped log message."""
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] [{level}] {msg}")

    def api_get(self, path: str) -> dict:
        """GET request to site API."""
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}") as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            self.log(f"GET {path} → {e.code}", "ERROR")
            return {}
        except Exception as e:
            self.log(f"GET {path} failed: {e}", "ERROR")
            return {}

    def api_post(self, path: str, body: dict) -> dict:
        """POST request to site API."""
        try:
            req = urllib.request.Request(
                f"{self.base_url}{path}",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            self.log(f"POST {path} → {e.code}", "ERROR")
            return {}
        except Exception as e:
            self.log(f"POST {path} failed: {e}", "ERROR")
            return {}

    def enrich_entry(self, entry: dict, db_context: dict) -> Optional[dict]:
        """
        Enrich a single entry using Claude reasoning.

        Generates:
        - signal: key takeaway
        - interpretation: what it means
        - pattern: recurring principle
        - lesson: principle learned
        - returned_action: concrete next step
        - first_step: first executable step
        - tracking_metric: observable to track
        - trackable_as: how to track it
        """
        raw = entry.get("raw_input", "").strip()
        if not raw:
            return None

        domain = entry.get("domain", "")
        entity = entry.get("entity", "")
        role = entry.get("signal_role", "watch")

        # Build context for Claude
        similar_entries = [
            e for e in db_context.get("entries", [])
            if e.get("domain") == domain and e.get("id") != entry.get("id")
        ][:5]

        context = f"""Domain: {domain}
Entity: {entity}
Signal Role: {role}

Raw Input:
{raw}

Similar entries in this domain for context:
{json.dumps([{"title": e.get("title"), "signal": e.get("signal"), "lesson": e.get("lesson")} for e in similar_entries], indent=2)}"""

        prompt = f"""Analyze this signal and enrich it with specific, actionable intelligence.

{context}

Return ONLY valid JSON, no other text. Fields:
{{
  "signal": "key takeaway (1-2 sentences, be specific)",
  "interpretation": "what this means for decisions",
  "pattern": "recurring principle",
  "lesson": "principle learned",
  "returned_action": "concrete next step",
  "first_step": "first executable step",
  "tracking_metric": "specific observable to prove impact",
  "trackable_as": "how to measure (metric/threshold/proof)"
}}"""

        try:
            # Try to use Claude via subprocess (Claude Code CLI)
            import subprocess
            result = subprocess.run(
                ["claude", "ask", prompt],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                # Parse Claude's response
                response_text = result.stdout.strip()
                # Extract JSON from the response
                try:
                    # Try to find JSON in the response
                    start = response_text.find("{")
                    end = response_text.rfind("}") + 1
                    if start >= 0 and end > start:
                        enriched = json.loads(response_text[start:end])
                        self.log(f"✓ Claude enriched {entry.get('id')[:20]}: {enriched.get('signal', '')[:50]}", "OK")
                        return enriched
                except json.JSONDecodeError:
                    pass
                # Fall through to fallback
                self.log(f"Claude parse failed. Using fallback for {entry.get('id')[:20]}", "WARN")
                return self._fallback_enrich(entry)
            else:
                self.log(f"Claude subprocess error. Using fallback for {entry.get('id')[:20]}", "WARN")
                return self._fallback_enrich(entry)

        except FileNotFoundError:
            self.log("Claude CLI not found. Using fallback enrichment.", "WARN")
            return self._fallback_enrich(entry)
        except subprocess.TimeoutExpired:
            self.log(f"Claude timeout for {entry.get('id')[:20]}. Using fallback.", "WARN")
            return self._fallback_enrich(entry)
        except Exception as e:
            self.log(f"Claude enrichment error: {e}. Using fallback.", "WARN")
            return self._fallback_enrich(entry)

    def _fallback_enrich(self, entry: dict) -> Optional[dict]:
        """Fallback enrichment using regex patterns (when Claude unavailable)."""
        raw = entry.get("raw_input", "").strip()
        role = entry.get("signal_role", "watch")
        domain = entry.get("domain", "")

        actions = {
            "action": "Execute the next step and track the outcome.",
            "watch": "Define trigger condition and review date. Resurface when triggered.",
            "pattern": "Note this pattern. Watch for repeats across domains.",
            "risk": "Identify failure mode. Define mitigation and metric to watch.",
            "opportunity": "Run smallest validation test. Track outcome.",
            "contradiction": "Compare against old belief. Update confidence with evidence.",
            "proof": "Attach proof artifact. Connect to relevant entries.",
            "preference": "Don't alert now. Resurface when context makes it useful.",
            "reference": "Link as reference. Resurface only when needed.",
            "archive": "Archive unless future trigger makes it actionable.",
        }

        first_words = raw.split()[:10]
        signal = f"{role.title()} in {domain}: {' '.join(first_words)}..."

        return {
            "signal": signal,
            "interpretation": f"This {role} signal requires attention in the {domain} domain.",
            "pattern": f"Recurring {role} signal pattern",
            "lesson": f"Track {role} signals in {domain}.",
            "returned_action": actions.get(role, "Execute the next step and log result."),
            "first_step": "Review this entry and decide next action.",
            "tracking_metric": "Signal tracked and acted upon",
            "trackable_as": "signal_tracking"
        }

    def detect_patterns(self, entries: list[dict]) -> list[dict]:
        """
        Detect cross-domain patterns from enriched entries.

        Returns list of pattern records with:
        - name: pattern name
        - domains: where it appears
        - entries: which entries show this pattern
        - lesson: unifying principle
        """
        if not entries:
            return []

        patterns = []

        # Pattern 1: High-signal entries across multiple domains
        domain_counts = {}
        for e in entries:
            d = e.get("domain", "Other")
            domain_counts[d] = domain_counts.get(d, 0) + 1

        if len(domain_counts) > 1:
            patterns.append({
                "name": "Cross-domain signal convergence",
                "domains": list(domain_counts.keys()),
                "count": len(entries),
                "lesson": "Multiple domains are generating signals on similar topics. Consider synthesis."
            })

        # Pattern 2: Action-heavy entries
        action_entries = [e for e in entries if e.get("signal_role") == "action"]
        if len(action_entries) >= 3:
            patterns.append({
                "name": "High action density",
                "count": len(action_entries),
                "lesson": "System is generating many actionable signals. Review routing and prioritization."
            })

        # Pattern 3: Watch/Risk clustering
        risk_entries = [e for e in entries if e.get("signal_role") in ("risk", "watch")]
        if len(risk_entries) >= 3:
            patterns.append({
                "name": "Risk monitoring cluster",
                "count": len(risk_entries),
                "lesson": "Multiple risks or watch-conditions active. System requires active monitoring."
            })

        # Pattern 4: Entity repetition
        entities = {}
        for e in entries:
            ent = e.get("entity", "").strip()
            if ent:
                entities[ent] = entities.get(ent, 0) + 1

        repeated_entities = [ent for ent, count in entities.items() if count >= 2]
        if repeated_entities:
            patterns.append({
                "name": f"Entity focus: {', '.join(repeated_entities[:3])}",
                "count": len(repeated_entities),
                "lesson": f"Signals cluster around key entities: {', '.join(repeated_entities[:3])}. These are high-leverage."
            })

        self.pattern_count += len(patterns)
        return patterns

    def process_queue(self):
        """
        Main processing loop:
        1. Fetch queue
        2. Enrich each entry
        3. Detect patterns
        4. Write back results
        """
        self.log("Fetching queue...", "DEBUG")
        queue_resp = self.api_get("/entries/queue")

        if not queue_resp or "error" in queue_resp:
            self.log("Queue fetch failed or empty", "WARN")
            return

        entries = queue_resp.get("entries", [])
        db_context = queue_resp.get("db_context", {})

        if not entries:
            self.log(f"Queue empty (0 pending)", "INFO")
            return

        self.log(f"Queue has {len(entries)} entries. Processing {min(len(entries), self.batch_size)}...", "INFO")

        # Enrich entries
        to_write = []
        for entry in entries[:self.batch_size]:
            enriched = self.enrich_entry(entry, db_context)
            if enriched:
                to_write.append({
                    "id": entry.get("id"),
                    **enriched,
                    "status": "codified"
                })
            time.sleep(0.5)  # Rate limit

        # Detect patterns from enriched entries
        patterns = self.detect_patterns(to_write)

        # Write back
        if to_write:
            self.log(f"Writing back {len(to_write)} enriched entries...", "INFO")
            batch_resp = self.api_post("/translate/batch", {"entries": to_write})
            if batch_resp.get("processed"):
                self.processed_count += batch_resp["processed"]
                self.log(f"✓ Processed {batch_resp['processed']} entries (total: {self.processed_count})", "OK")
            if batch_resp.get("errors"):
                self.log(f"⚠ {batch_resp['errors']} errors", "WARN")

        if patterns:
            self.log(f"Detected {len(patterns)} patterns: {', '.join([p.get('name', '') for p in patterns])}", "INFO")

    def run(self):
        """Run the processor daemon."""
        self.log(f"Starting processor (interval: {self.interval}s, batch: {self.batch_size})", "INFO")
        self.log(f"Connecting to {self.base_url}", "DEBUG")

        try:
            while True:
                self.process_queue()
                self.log(f"Sleeping {self.interval}s...", "DEBUG")
                time.sleep(self.interval)
        except KeyboardInterrupt:
            self.log("Shutting down...", "INFO")
            self.log(f"Processed {self.processed_count} entries, detected {self.pattern_count} patterns", "INFO")
            sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="Info Analyzer computational layer — local processing daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 processor.py                           # Run with defaults (60s interval, batch size 10)
  python3 processor.py --interval 30 --batch 5  # Run every 30s, process 5 entries per run
  python3 processor.py --url http://remote:8000/api  # Process a remote site
        """
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000/api", help="Site API base URL")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between processing runs")
    parser.add_argument("--batch-size", type=int, default=10, help="Entries to process per run")

    args = parser.parse_args()

    processor = Processor(
        base_url=args.url,
        interval=args.interval,
        batch_size=args.batch_size
    )
    processor.run()


if __name__ == "__main__":
    main()
