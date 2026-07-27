
# Engineering Standard: Service Smoke Tests

Every deployable Flowtona service **must** provide a smoke test
located at:

```
scripts/smoke_test.sh
```

Compliance with this standard is mandatory for all production
services. This isn't a suggestion per service — it's a baseline every
service starts with, so operational maturity doesn't depend on each
service reinventing it.

## Purpose

Smoke tests provide deployment verification by exercising a running
service over real HTTP. They complement, but do not replace, the
service's own automated unit, integration, and functional test suites.

Their purpose is to answer one question:

> "Can I safely consider this deployed service operational?"

## Requirements

- **Configurable target.** A `BASE_URL` environment variable (or
  equivalent), defaulting to a sensible local value. The same script
  must run unmodified against a local dev instance, a container, a
  Kubernetes deployment, or a CI-spun-up instance.
- **Real HTTP, not in-process.** This tests the actual running
  artifact over the network, the way an operator or monitoring system
  would hit it — it is not a substitute for the service's own
  in-process test suite (pytest or equivalent), which tests different
  things.
- **Exit code is the contract.** `0` only if every check passed;
  non-zero otherwise. This is what makes the script usable as a CI
  gate, not just a script a human reads the output of.
- **Collect all failures, don't stop at the first.** A smoke test is
  most useful when one run tells you everything that's broken, not
  just the first thing.
- **Validate the operational surface** — at minimum, health/readiness/
  startup probes and any service metadata/metrics endpoints the
  service exposes.
- **Validate at least one real business workflow**, not just that the
  process is alive. For identity-service, this means the actual
  authentication flow (signup, login, token refresh, logout) — not
  merely that `/healthz` returns 200.
- **Validate the error contract where applicable** — if the service
  uses a standard error shape (e.g. RFC 9457), the smoke test should
  confirm a real error response actually has that shape, not just the
  right status code.
- **Clean up after itself.** A smoke test run should not leave behind
  state (e.g. an orphaned session, a stray record) that changes the
  outcome of the next run against the same target.
- **Portable across the expected runtime targets.** In Flowtona's case
  today, that means Linux and macOS — avoid platform-specific tooling
  (e.g. GNU-only `date` extensions) where a portable equivalent exists
  (e.g. `curl`'s own request timer) without real added complexity.

## Non-requirements

- It does not need to be exhaustive. A smoke test proves the service
  is fundamentally working, not that every edge case behaves
  correctly — that's what the service's own test suite is for.
- It does not need a shared helper library across services until there
  are enough services to justify one. Duplication across one or two
  services is not a problem worth solving in advance.

## Reference implementation

`apps/services/identity-service/scripts/smoke_test.sh` is the first
implementation of this standard and can be used as a starting template
for new services — copy and adapt its structure (operational checks,
a business-flow section, an error-contract section, `pass`/`fail`
counters, a summary line) rather than designing each new one from
scratch.