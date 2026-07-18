
# identity-service — Operator Guide

## Overview

Authentication and authorization service for the Flowtona platform.
See `identity-service-overview.md` for the architecture summary.

**Current status:** domain models, repositories, and the core service
layer (users, tenants, memberships, invitations, email verification,
refresh tokens) are implemented and tested. HTTP routes and the
orchestration layer (`AuthService`) are not yet built — this service is
not yet runnable as a standalone API. Everything below reflects what's
actually usable today: running the test suite and quality checks.

## Prerequisites

- Python 3.12
- `pip`

## Setup

```bash
cd apps/services/identity-service
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
```

`requirements-dev.txt` includes `requirements.txt`, so this installs
both runtime and development dependencies in one step.

## Configuration

Settings load from environment variables with sensible local defaults
(`app/core/config.py`). For local development, create a `.env` file in
`apps/services/identity-service/` to override any default — none are
required to run the test suite, since nothing in the current test
coverage depends on a real environment (all repositories are in-memory
for this phase).

## Running the test suite

```bash
source venv/bin/activate

# Full suite
pytest tests -q

# With verbose output
pytest tests -v

# A specific layer
pytest tests/unit/repositories -v
pytest tests/unit/services -v

# Security-specific tests (password hashing, token hashing)
pytest tests/security -v
```

## Code quality checks

Run all three before committing — this is the standard check sequence
used throughout this project's development:

```bash
ruff format app/ tests/
ruff check app/ tests/
mypy app tests
```

## Project structure

```
app/
├── constants/      # Fixed roles and permissions
├── core/           # Configuration
├── exceptions/      # Domain exceptions (one file per entity)
├── models/          # Domain entities (Pydantic v2)
├── repositories/     # Persistence Protocols + in-memory implementations
├── security/         # Password hashing, token hashing/generation
└── services/          # Business logic (one service per entity, plus
                        # AuthService — not yet implemented — for
                        # workflows spanning multiple services)
tests/
├── unit/repositories/  # Repository behavior tests
├── unit/services/      # Service behavior tests
├── unit/                # Domain model tests
└── security/            # Password/token hashing tests
```

## Running locally

Not yet possible — there's no HTTP entry point wired up yet
(`app/main.py` exists but has no routes registered, and `AuthService`,
which the routes will depend on, hasn't been built). This section will
be filled in once routes exist.

## Contributing

This service follows GitFlow (`feature/* → develop → main`). Each
change lands as its own PR against `develop`, with `ruff`, `mypy`, and
`pytest` all passing before merge.