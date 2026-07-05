# Info Analyzer Computational Layer

Your local device is now the **brain** of the system. The processor runs as a background daemon that:

1. **Enriches entries** — takes raw dumps and generates signal → lesson using Claude reasoning
2. **Detects patterns** — finds cross-domain signals and themes
3. **Writes results back** — automatically updates the database

The site is now a **memory + UI layer**. Computation happens locally on your device.

---

## How It Works

```
User dumps data
      ↓
   [Site API]
      ↓
 Queue DB entries
      ↓
[Local Processor] ← YOU RUN THIS
      ↓
Claude enriches (reasoning)
      ↓
Auto-writes back to DB
      ↓
   [Site UI]
      ↓
User sees enriched entries
```

---

## Quick Start

### 1. Run the processor (continuous mode)

```bash
cd info_analyzer_os_sqlite_v0_3_clean
python3 processor.py
```

This runs forever. Every 60 seconds:
- Fetches queue from site
- Processes up to 10 entries with Claude
- Detects patterns
- Writes results back
- Shows logs

### 2. Run with custom settings

```bash
# Process every 30 seconds, 5 entries per batch
python3 processor.py --interval 30 --batch-size 5

# Process a remote site
python3 processor.py --url http://remote-server:8000/api --interval 20
```

### 3. Stop the processor

Press `Ctrl+C`. It shows a summary of what it processed.

---

## What Claude Does (Enrichment)

For each queued entry, Claude generates:

| Field | What It Means |
|-------|---------------|
| **signal** | Key takeaway from raw input |
| **interpretation** | What this means for your decisions |
| **pattern** | Recurring principle |
| **lesson** | Principle learned |
| **returned_action** | Concrete next step to take |
| **first_step** | First executable step |
| **tracking_metric** | Observable to prove impact |
| **trackable_as** | How to measure it |

Example:
```
Raw Input: "Realized: 500 hours of deliberate use = tool fluency"

Signal: "Tool fluency requires deep practice, not ownership"
Lesson: "Invest 500+ hours before claiming mastery of any tool"
Action: "Schedule weekly Claude sessions: 2h focused practice"
Metric: "# Claude sessions per week + feature depth"
```

---

## What Claude Does (Pattern Detection)

The processor scans enriched entries and identifies:

1. **Cross-domain convergence** — Same signals appearing in multiple domains
2. **Action density** — High concentration of actionable signals
3. **Risk clusters** — Multiple risks/watches active (system needs monitoring)
4. **Entity focus** — Signals clustering around key entities (high-leverage targets)

Example pattern:
```
📊 Cross-domain signal convergence
Domains: Business, Career, AI Project
Lesson: Multiple domains generating similar signals. 
        Consider synthesis — these may be the same underlying pattern.
```

---

## What Happens to the Site UI

As the processor runs, you'll see:

- **Queue count decreases** — badge updates in real-time
- **Entry status changes** — `⬦ Queued` → `◆ AI Enriched`
- **Enrichment badges appear** — Interpretation and Lesson fields populate
- **New patterns added** — Pattern tab shows cross-domain insights
- **Actions become concrete** — Generic actions become specific

You don't need to do anything. Just keep the processor running and the site will stay current.

---

## Architecture Benefits

### Before (manual, CRUD-only)
```
User → Dump → DB
User must manually run Claude Code
User must manually write results back
UI is static snapshot
```

### After (computational layer)
```
User → Dump → DB
       ↓
  [Auto processing]
       ↓
  [Auto write-back]
       ↓
   UI updates live
```

---

## Logs & Monitoring

The processor prints timestamped logs:

```
[19:14:31] [INFO] Starting processor (interval: 60s, batch: 10)
[19:14:31] [DEBUG] Connecting to http://127.0.0.1:8000/api
[19:14:31] [INFO] Queue has 15 entries. Processing 10...
[19:14:32] [OK] ✓ Claude enriched IA-2606290829-A51B: Risk in Business...
[19:14:33] [OK] ✓ Claude enriched IA-2606290829-7F37: Risk in Career...
[19:14:35] [INFO] Writing back 2 enriched entries...
[19:14:36] [OK] ✓ Processed 2 entries (total: 42)
[19:14:36] [INFO] Detected 1 patterns: Cross-domain signal convergence
[19:14:36] [DEBUG] Sleeping 60s...
```

---

## Fallback Mode

If Claude CLI is unavailable, the processor uses **regex-based enrichment** as a fallback:

```
[19:14:31] [WARN] Claude CLI not found. Using fallback enrichment.
[19:14:31] [OK] ✓ Fallback enriched IA-2606290829-A51B: [generic signal]
```

This keeps the system working, but results are less specific. To use real Claude:

```bash
# Check if Claude CLI is installed
which claude

# If not installed, install via npm
npm install -g @anthropic-ai/claude-code

# Or run Claude Code IDE and make sure "claude" command is available
claude --version
```

---

## Running in Background (Optional)

To run the processor in the background permanently:

### macOS (using launchd)
```bash
# Create a plist file
cat > ~/Library/LaunchAgents/com.infoanalyzer.processor.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.infoanalyzer.processor</string>
  <key>ProgramArguments</key>
  <array>
    <string>python3</string>
    <string>/path/to/info_analyzer_os_sqlite_v0_3_clean/processor.py</string>
    <string>--interval</string>
    <string>60</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/processor.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/processor.log</string>
</dict>
</plist>
EOF

# Load it
launchctl load ~/Library/LaunchAgents/com.infoanalyzer.processor.plist

# Check status
launchctl list | grep processor

# View logs
tail -f /tmp/processor.log
```

### Linux (using systemd)
```bash
sudo cat > /etc/systemd/user/infoanalyzer.service << 'EOF'
[Unit]
Description=Info Analyzer Computational Layer
After=network.target

[Service]
Type=simple
ExecStart=python3 /path/to/info_analyzer_os_sqlite_v0_3_clean/processor.py
Restart=always

[Install]
WantedBy=default.target
EOF

systemctl --user enable infoanalyzer
systemctl --user start infoanalyzer
journalctl --user -u infoanalyzer -f
```

---

## Stopping the Processor

```bash
# Keyboard interrupt (Ctrl+C)
# Shows final stats:
Shutting down...
Processed 42 entries, detected 5 patterns
```

Or kill by process ID:
```bash
ps aux | grep processor
kill <PID>
```

---

## Next Steps

1. **Run it now**: `python3 processor.py`
2. **Watch the queue disappear** from the site (entries get enriched)
3. **See enrichment badges** appear on entry cards
4. **Watch patterns emerge** in the Patterns tab
5. **Adjust settings** if needed (faster: `--interval 30`, more entries: `--batch-size 20`)

The computational layer is now **local, autonomous, and always running**.
