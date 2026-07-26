
# identity-service

Authentication and authorization service for the Flowtona platform —
signup, login, session management (short-lived access tokens paired
with rotating refresh tokens), email verification, and tenant
invitations across Flowtona's multi-tenant model, where a single user
may belong to more than one business.

**Status:** Phase 1 feature-complete and runnable — the full domain
model, all entity services, `AuthService` orchestration, and every
HTTP route (account entry, sessions, verification, invitations) are
implemented and tested, along with a full operational layer (health
probes, metadata, JWKS publication, Prometheus metrics). Repositories
are in-memory; PostgreSQL is deliberately deferred to a later phase.

## Documentation

- **[Architecture Overview](./docs/identity-service-overview.md)** —
  what this service does, its internal layering, and its core design
  principles.
- **[Operator Guide](./docs/identity-service-operator-guide.md)** —
  install, run, verify, and troubleshoot the service locally.

## Quick start

```bash
cd apps/services/identity-service
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
python scripts/generate_signing_keypair.py
uvicorn app.main:app --reload
```

Then visit `http://localhost:8000/docs` for interactive API docs, or
see the Operator Guide for a full manual smoke test.

## Part of

[Flowtona](../../../README.md) — a B2B SaaS Business Operating System
for field service businesses, under the ElphMora ecosystem.