"""
app/metrics/auth_metrics.py

JWT verification metrics -- separated from business_metrics.py,
matching client-service's own file split (security/diagnostic
concerns vs. business/request-outcome concerns). Registered against
app/metrics/registry.py's shared REGISTRY (the default global
Prometheus registry), same as every other metric in this codebase --
see that module's docstring for why a split registry would be a real
bug, not a style choice.
"""

from prometheus_client import Counter

JWT_VERIFICATION_FAILURES_TOTAL = Counter(
    "jwt_verification_failures_total",
    "Total JWT verification failures, by reason.",
    labelnames=("reason",),
)
