# client-service

Client relationship management for the Flowtona platform — clients,
the sites they operate, and the contacts at each, for field service
businesses managing work across multiple locations and points of
contact.

**Status:** Phase 1 feature-complete and runnable — full CRUD for all
three resources (clients, sites, contacts), tenant and cross-client
isolation, business metrics, and a full operational layer (health
probes, metadata, Prometheus metrics) are implemented and tested.
Repositories are in-memory; PostgreSQL is deliberately deferred to a
later phase. client-service issues no tokens of its own — it verifies
access tokens issued by identity-service via JWKS.

## Documentation

- **[Architecture Overview](./docs/client-service-overview.md)** —
  what this service does, its internal layering, and its core design
  principles.
- **[Operator Guide](./docs/client-service-operator-guide.md)** —
  install, run, verify, and troubleshoot the service locally.

## Quick start

```bash
cd apps/services/client-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:create_app --factory --reload
```

No signing keypair to generate — unlike identity-service,
client-service issues no tokens; it only verifies ones identity-service
already issued, fetching identity-service's public signing key over
the network (JWKS) the first time it's needed. See the Operator Guide
for what that means for running fully authenticated routes locally.

Then visit `http://localhost:8000/docs` for interactive API docs, or
see the Operator Guide for a full manual smoke test.

## Part of

[Flowtona](../../../README.md) — a B2B SaaS Business Operating System
for field service businesses, under the ElphMora ecosystem.