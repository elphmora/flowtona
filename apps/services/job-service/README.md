# job-service

Operational source of record for field work — Job/Visit lifecycle,
cross-service snapshotting from client-service, and domain events for
the Flowtona platform, for field service businesses tracking work
through to completion.

**Status:** Phase 0 (Service Foundation) — operational endpoints only
(health probes, metadata, Prometheus metrics). No domain routes, no
JWT verification yet; both arrive with Phase 1 (Create Job).
Repositories will be in-memory when they land in Phase 1; PostgreSQL
is deliberately deferred to a later phase, matching identity-service
and client-service. job-service issues no tokens of its own — like
client-service, it will verify access tokens identity-service already
issued, via JWKS, once Phase 1 introduces the first protected route.

## Quick start

```bash
cd apps/services/job-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:create_app --factory --reload
```

No signing keypair to generate, and nothing to authenticate against
yet — Phase 0 has no protected routes.

Then visit `http://localhost:8000/docs` for interactive API docs.

## Tests

```bash
pytest
```

## Part of

[Flowtona](../../../README.md) — a B2B SaaS Business Operating System
for field service businesses, under the ElphMora ecosystem.