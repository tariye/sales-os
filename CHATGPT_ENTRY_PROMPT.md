# ChatGPT → Info Analyzer OS JSON Prompt

Use this in any ChatGPT chat when you want to save a rep to the SQLite database.

```text
Convert the following into an Info Analyzer OS JSON entry.

Core law: Non-trackable signal is useless. Make every signal trackable and actionable.

Return valid JSON only. No markdown.

Schema:
{
  "date": "YYYY-MM-DD",
  "domain": "Lab | Investing | Business | Career | Fitness | Network+ | Music | AI Project | Personal Finance | Other",
  "entity": "company/system/person/role/song/protocol/product/etc",
  "source_type": "chatgpt | manual | article | lab event | job post | financial statement | workout | music | other",
  "raw_input": "original or summarized raw input",
  "signal": "what matters",
  "interpretation": "what the signal means",
  "signal_role": "action | watch | pattern | risk | opportunity | contradiction | proof | archive",
  "trackable_as": "metric, behavior, threshold, proof artifact, trigger condition, repeat count, etc",
  "tracking_metric": "specific observable that proves whether this signal matters",
  "baseline": "current state, if known",
  "target_threshold": "what change matters, if known",
  "trigger_condition": "when this memory should resurface",
  "review_date": "YYYY-MM-DD or empty string",
  "pattern": "recurring principle this may belong to",
  "returned_action": "concrete next action",
  "result": "empty unless already known",
  "lesson": "principle learned",
  "next_step": "what should happen next",
  "confidence": "Low | Medium | High",
  "status": "raw | codified | watching | validated | weakened | upgraded | superseded | archived",
  "tags": ["tag1", "tag2"],
  "proof_artifact": "optional proof artifact"
}

Input:
[paste raw chat/notes here]
```

Then save it with:

```bash
curl -X POST http://127.0.0.1:8000/api/entries \
  -H "Content-Type: application/json" \
  -d @entry.json
```
