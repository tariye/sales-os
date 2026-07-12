# Loop Principle

Status: Active engineering doctrine

## Rule

No feature ships until it survives the live user loop.

The loop is:

```text
Build -> Run -> Use -> Observe -> Fix -> Retest -> Document -> Commit
```

For Info Analyzer OS, "works" means the user can complete the intended job inside the product. A passing implementation must prove that a real user can:

- input real information
- get contextual intelligence back
- take or track an action
- save the result into memory
- resurface that memory later

## Required Cycle

1. **Build** the smallest usable version.
2. **Run** the local site or service.
3. **Use** the feature through the UI or public API.
4. **Observe** where the flow breaks.
5. **Fix** the failure.
6. **Retest** the same path.
7. **Document** the outcome with changelog, ADR, or proof JSON.
8. **Commit** code and proof together.

## Acceptance Test

Every feature should pass this question:

```text
Can I input real information, get contextual intelligence back, take or track an action, and save the result into memory?
```

If the answer is no, the feature is not done.

## Executable Check

Run:

```bash
python3 tools/loop_check.py --base-url http://127.0.0.1:8000 --stock AAPL
```

Optional proof output:

```bash
python3 tools/loop_check.py --write-proof docs/proof/latest-loop-check.json
```

The checker validates:

- health endpoint
- Command Center resolver buttons
- Pull Engine on a sales query
- Stock Intel on a ticker
- write -> pull -> log result -> delete cleanup loop for a temporary memory entry

## Operating Doctrine

```text
No feature ships until it survives the loop.
No signal matters until it is trackable.
No memory matters until it can resurface.
No cockpit warning matters until it gives the operator a control.
```

