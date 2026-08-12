"""
app/metrics/auth_metrics.py

JWT verification failure metrics — kept separate from
app/metrics/business_metrics.py, which is specifically for domain
business events (a client was created, archived, etc). This is
auth/security infrastructure, closer in kind to why TokenVerifier
lives outside ServiceRegistry than to anything ClientService owns.
"""

from prometheus_client import Counter

JWT_VERIFICATION_FAILURES_TOTAL = Counter(
    "jwt_verification_failures_total",
    "Total JWT verification failures, by reason. See "
    "app/security/token_verifier.py's module docstring for exactly "
    "which failure modes map to which reason value, and why some "
    "distinct PyJWT exception types are deliberately grouped under one "
    "reason rather than split further.",
    ["reason"],
)

# The specific reason values ("malformed_token", "key_resolution_failed",
# "expired", "invalid_claims", "wrong_token_type",
# "malformed_application_claims") are an operational contract, not an
# implementation detail — any dashboard or alert built against this
# metric will filter or group by these exact strings. Renaming one
# (e.g. "invalid_claims" -> "jwt_invalid") or splitting a category
# further silently breaks that tooling without erroring anywhere in
# this codebase. Changing the label set is a real decision, not a
# casual rename — update this comment, token_verifier.py's docstring,
# and client-service-architecture.md's Entity & Convention
# Clarifications together, in the same change, not just the code.
