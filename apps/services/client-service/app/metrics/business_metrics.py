"""
app/metrics/business_metrics.py

Domain-specific counters named in 01-api-contract.md — distinct from
app/middleware/metrics.py's generic HTTP request/latency metrics.
Each counter lives with the operation that owns it (per the branch
mapping in client-service-architecture.md): client counters here are
incremented from app/api/v1/clients.py and ClientService directly, not
from generic middleware, since "a client was created" isn't an HTTP
concept — it's a domain event a route happens to trigger.

jwt_verification_failures_total{reason} is deliberately NOT defined
here — see client-service-architecture.md's Deferred Decisions and
platform-conventions.md §14 for why, and the dedicated follow-up
branch where that gets resolved.
"""

from prometheus_client import Counter

CLIENT_CREATED_TOTAL = Counter(
    "client_created_total",
    "Total clients created",
)

CLIENT_ARCHIVED_TOTAL = Counter(
    "client_archived_total",
    "Total clients archived",
)

CLIENT_ARCHIVED_WRITE_REJECTED_TOTAL = Counter(
    "client_archived_write_rejected_total",
    "Total writes rejected because the target client is archived. "
    "Incremented at two points in ClientService: "
    "require_writable_client() (the shared guard SiteService/"
    "ContactService also call before their own writes, once those "
    "exist) and update_client()'s own independent path to the same "
    "outcome (it catches the repository's archived-check directly, "
    "not via require_writable_client()).",
)

PERMISSION_DENIED_TOTAL = Counter(
    "permission_denied_total",
    "Total requests rejected for insufficient permission",
    ["permission"],
)
