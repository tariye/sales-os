# Gate 3B Source Observation Contract

Gate 3B connects externally observed financial source facts to the Gate 3A reliability foundation.

## Supported Caller

The supported caller is a trusted ChatGPT/MCP session or trusted automation that can provide observed source fields to the local MCP bridge.

The local Python process does not have direct bank, payment, or ChatGPT Finances API access. It records observations it is given. It does not poll financial institutions, move money, approve allocations, or infer that a source worker is running.

## Supported Source Fields

`record_financial_source_observation` accepts:

- `source_system_id`
- `source_connection_id`
- `account_external_id`
- `source_transaction_id`
- `observation_status`
- `observed_at`
- `amount_cents`
- `currency`
- `account_name`
- `classification`
- `classification_confidence`
- `effective_date`
- `posted_at`
- `source_name`
- `observation_type`
- `economic_inflow_key`
- `provider_transaction_id`
- `provider_pending_id`
- `provider_posted_id`
- `source_modified_at`
- `metadata`
- `confirmed`

The identity scope is:

`source_system_id + source_connection_id + account_external_id + source_transaction_id`

The economic inflow scope is:

`source_system_id + source_connection_id + account_external_id + economic_inflow_key`

## Behavior

Pending observations are persisted as `pending` source observations and do not create `financial_inflow_posted` events.

Posted observations are persisted as source observations and, if the economic inflow has not already been ingested, pass through:

`core_source_observations -> core_events -> EventDispatcher -> core_signals -> core_alerts`

Exact retries return the existing observation/result. Legitimate source corrections create a new observation version without duplicating the same economic inflow signal/alert.

`get_source_observation_status` is read-only and returns pending observations even when no `event_id` exists.

## Access Gap

The current system can receive financial observations through MCP. It does not yet prove scheduled or unattended access to ChatGPT Finances or a bank provider. Activation of a caller/poller remains future work.
