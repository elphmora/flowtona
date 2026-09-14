"""
app/metrics/registry.py

Re-exports prometheus_client's own default global REGISTRY, rather
than constructing a dedicated CollectorRegistry(). This is a
deliberate correction: an earlier draft created its own isolated
registry here, while app/middleware/metrics.py's Counter()/Histogram()
objects register into prometheus_client's global default by default
(no explicit registry= kwarg needed) — using two different registries
would mean requests get measured into one registry while GET /metrics
exposes a permanently-empty other one, with no error to signal the
mismatch. Importing and re-exporting the SAME default global object
here guarantees every metric defined anywhere in this codebase (this
module, app/middleware/metrics.py, and Phase 10's future business
counters) lands in the one registry GET /metrics actually reads from.

Phase 0/1: no domain counters registered yet. Phase 10 (Observability)
adds job_created_total, visit_completed_total{outcome_code}, and the
rest of 03-api-contract.md's named counters — defined in their own
module (app/metrics/business_metrics.py, matching client-service's
naming), imported from here for the shared registry reference.
"""

from prometheus_client import REGISTRY

__all__ = ["REGISTRY"]
