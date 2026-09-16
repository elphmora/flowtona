"""
app/metrics/business_metrics.py

Matches client-service's own file split -- business/request-outcome
metrics, separate from auth_metrics.py's security/diagnostic ones.
Only PERMISSION_DENIED_TOTAL exists here for now; Phase 10
(Observability, per 07-implementation-plan.md) adds job_created_total
and the rest of 03-api-contract.md's named counters -- not built
speculatively ahead of that phase.
"""

from prometheus_client import Counter

PERMISSION_DENIED_TOTAL = Counter(
    "permission_denied_total",
    "Total requests rejected for insufficient permission, by permission.",
    labelnames=("permission",),
)
