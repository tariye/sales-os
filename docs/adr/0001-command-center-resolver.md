# ADR 0001: Command Center Resolver

Date: 2026-07-11

Status: Accepted

## Context

Info Analyzer OS had a working Command Center, Pull Engine, Actions queue, dormant detector, and Pattern Engine. The gap was operator execution. The cockpit could identify pressure such as action backlog, result backlog, stale surfaced cards, and queue items, but the user still had to manually navigate elsewhere to resolve them.

That violated the working principle:

> Non-trackable signal is useless. Make every signal trackable and actionable.

If the cockpit only reports a problem but does not provide the next control, it is still partly a dashboard rather than an operating surface.

## Decision

The Command Center will treat each cockpit callout as a resolver card.

Each callout can carry structured button metadata:

```json
{
  "label": "Review Actions",
  "action": "show_actions",
  "value": ""
}
```

The frontend maps those actions to concrete UI behavior:

- open the Actions tab
- open the Queue tab
- open Memory with a search value
- run dormant detection
- run the Pattern Engine
- run memory rewiring
- focus the Pull query
- clear surfaced cards

Market/resale Sales OS signals are also separated from CRM pipeline signals so sales pull cards use the right tracking metric.

## Consequences

The Command Center now behaves more like a cockpit:

- warning/caution/advisory cards expose controls at the point of need
- backlog pressure can be resolved from the cockpit
- stale surfaced cards can be cleared without database work
- sales pull results are more decision-relevant
- startup is faster because full contextual rewiring is user-triggered, not automatic

Tradeoff: resolver actions are currently hardcoded frontend handlers. That is acceptable for v0.72 because it keeps behavior explicit and easy to audit. A later version can centralize resolver action definitions if the action set grows.

