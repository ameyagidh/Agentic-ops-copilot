# Runbook: downstream dependency degradation

## Symptoms
Timeouts or errors calling a downstream service, with no corresponding
errors originating in this service's own code paths. Often no recent deploy.

## Likely causes
- The dependency itself is degraded or down.
- A network partition or DNS issue between this service and the dependency.
- Missing/misconfigured circuit breaker or timeout causing cascading failure.

## Recommended actions
1. Check the dependency's own health/status page or dashboards.
2. If the dependency is confirmed down, engage its on-call and consider
   enabling a fallback/circuit breaker to shed load.
3. If healthy, check network-level metrics (DNS, connection resets) between
   the two services.
