# Enterprise browser-agent operations

The additive enterprise layer separates durable policy, replay, takeover, workflow, fleet, and evaluation invariants from FastAPI delivery. SQLite tables use `CREATE TABLE IF NOT EXISTS`; rollback disables the new routes and preserves data. Existing Browser Helper endpoints and response envelopes remain available.

Security is fail-closed: navigation authorization resolves host addresses and rejects loopback, private and link-local destinations before CDP dispatch; replay payloads redact common secrets; takeover leases expire; fleet leases enforce tenant quotas; only checkpointed sessions are recoverable. Production requires deployment identity, object-level authorization, egress enforcement and managed encryption.

The consoles provide skip navigation, visible keyboard focus, responsive layouts, empty state, live status and explicit recovery guidance. Completed work remains preserved when an operation is retried.
