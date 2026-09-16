"""
app/constants/permissions.py

job-service's own permission string constants -- the literal strings
this service checks for in a verified token's permissions claim.
Deliberately NOT imported from identity-service (Platform Conventions
§12) -- same reasoning as client-service's own constants/permissions.py:
this service only needs to know the exact strings it checks for.

CLIENTS_READ is a genuine divergence from client-service's pattern: it's
Client Service's own permission namespace, not Job Service's. Job
Service pre-checks it on the caller's token before forwarding that
token to Client Service (platform-conventions.md §11 Amendment 7), but
does not own or define its meaning. Deliberately NOT imported from
client-service's own constants file either (Job Service never imports
another service's Python code, 01-domain-foundations.md §9) -- defined
locally instead.

RequiredPermission = JobPermission | Literal["clients:read"] -- added
during a post-green architectural review, not present in the first
version of this file. That version typed require_permission() as
plain `str`, needed because Create Job pre-checks BOTH jobs:write
(this service's own permission) AND clients:read (the foreign one)
through a single factory -- but `str` gave up ALL static type-checking
at every call site, not just the safety needed for the one foreign
case. This Union restores it: a typo like require_permission
("jobs:writ") is a mypy error again, while require_permission
(CLIENTS_READ) still type-checks correctly.
"""

from typing import Literal

JobPermission = Literal["jobs:read", "jobs:write"]

JOBS_READ: JobPermission = "jobs:read"
JOBS_WRITE: JobPermission = "jobs:write"

CLIENTS_READ: Literal["clients:read"] = "clients:read"

RequiredPermission = JobPermission | Literal["clients:read"]
