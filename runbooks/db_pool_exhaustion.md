# Runbook: database connection pool exhaustion

## Symptoms
Elevated 5xx rate, p99 latency several times baseline, log lines containing
`ConnectionPoolTimeoutError` or "connection pool exhausted".

## Likely causes
- A recent deploy increased per-request DB connection usage (e.g. removed
  connection pooling, added N+1 queries).
- Traffic spike beyond what the configured pool size supports.
- A slow query or lock holding connections open longer than usual.

## Recommended actions
1. Check pool size/utilization metrics against configured max connections.
2. If a deploy correlates with onset, roll it back first.
3. If not deploy-correlated, temporarily raise the pool size and check for
   long-running or blocked queries on the primary database.
