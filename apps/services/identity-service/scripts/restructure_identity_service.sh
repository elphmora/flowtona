#!/usr/bin/env bash
# Restructures the identity-service scaffold to align with the Flowtona ADR.
# Safe to run because every file involved is currently empty scaffold (confirmed 2026-07-12).
# Run from inside the identity-service/ directory.
set -euo pipefail

if [[ ! -d app || ! -d tests || ! -f app/main.py ]]; then
  echo "Error: run this from the identity-service root."
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Error: this directory is not inside a Git repository."
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Error: working tree is not clean."
  echo "Commit or stash existing changes before restructuring."
  git status --short
  exit 1
fi

echo "== 1. Renaming organisation -> tenant (matches ADR terminology exactly) =="
git mv app/models/organisation.py            app/models/tenant.py
git mv app/repositories/organisation_repository.py app/repositories/tenant_repository.py
git mv app/services/organisation_service.py   app/services/tenant_service.py
git mv app/exceptions/organisation.py         app/exceptions/tenant.py
git mv app/schemas/organisation.py            app/schemas/tenant.py

echo "== 2. Renaming session -> refresh_token =="
echo "   (single entity with a family_id field — NOT split into session+token."
echo "    See ADR Invariant 10: a user may hold multiple concurrent families"
echo "    per tenant, one per device/login. logout-all revokes all active"
echo "    tokens for (user_id, tenant_id) in one operation, not a single family.)"
git mv app/models/session.py                  app/models/refresh_token.py
git mv app/repositories/session_repository.py app/repositories/refresh_token_repository.py
git mv app/services/session_service.py        app/services/refresh_token_service.py
git mv app/schemas/session.py                 app/schemas/refresh_token.py

echo "== 3. Removing permission/role persistence (not a stored entity per Decision 5) =="
git rm app/models/permission.py
git rm app/models/role.py
git rm app/repositories/permission_repository.py
# services/permission_service.py stays — it owns real authorization policy:
# role-to-permission resolution, email-verification soft gating, and the effect
# of inactive, suspended, or revoked memberships on effective permissions.

echo "== 4. Removing api_key scaffolding (undesigned, sits in Deferred Decisions) =="
git rm app/auth/api_key.py
git rm app/models/api_key.py
git rm app/repositories/api_key_repository.py
git rm app/services/api_key_service.py
git rm app/schemas/api_key.py

echo "== 5. Creating dedicated security/ package (Decision 8 amendment) =="
mkdir -p app/security
touch app/security/__init__.py
git mv app/utils/security.py app/security/hashing.py
git mv app/auth/jwt.py       app/security/jwt.py
touch app/security/secret_provider.py
echo "  NOTE: app/auth/ retains request-authentication concerns (dependencies.py"
echo "  already exists there) — it now calls into app/security/jwt.py for the"
echo "  actual cryptographic verification, rather than owning that logic itself."
echo "  NOTE: review app/security/hashing.py's prior content once implementing;"
echo "  it may need splitting further depending on what's already in there."

echo "== 6. Moving operational endpoints out of /v1 (API contract correction) =="
git mv app/api/v1/health.py  app/api/system_health.py
git mv app/api/v1/meta.py    app/api/system_meta.py
git mv app/api/v1/metrics.py app/api/system_metrics.py
echo "  NOTE: wire these into main.py as root-level routes (/healthz, /readyz,"
echo "  /startupz, /info, /metrics), NOT included in the /v1 router. Update"
echo "  app/api/v1/router.py to remove references to health/meta/metrics."

echo "== 7. Adding missing v1 route files =="
echo "   (no tenants.py — the API contract has no top-level tenant CRUD,"
echo "    only the nested POST /v1/tenants/{tenant_id}/invites, which lives"
echo "    in invites.py)"
touch app/api/v1/users.py
touch app/api/v1/invites.py

echo "== 8. Adding Protocol/implementation split for repositories (Decision 9) =="
mkdir -p app/repositories/in_memory
touch app/repositories/in_memory/__init__.py
touch app/repositories/in_memory/user_repository.py
touch app/repositories/in_memory/tenant_repository.py
touch app/repositories/in_memory/membership_repository.py
touch app/repositories/in_memory/refresh_token_repository.py
touch app/repositories/in_memory/invitation_repository.py
echo "  NOTE: files directly under repositories/ (e.g. user_repository.py)"
echo "  become the Protocol definitions; repositories/in_memory/*.py holds"
echo "  the Phase 1 concrete implementations satisfying those Protocols."

echo "== 9. Adding mandatory security test category (Decision 16) =="
mkdir -p tests/security
touch tests/security/__init__.py

echo "== 10. Removing empty utils/ package only if now unused =="
if [[ -z "$(find app/utils -type f ! -name '__init__.py' -print -quit 2>/dev/null)" ]]; then
  git rm app/utils/__init__.py 2>/dev/null || true
  rmdir app/utils 2>/dev/null || true
fi

echo
echo "Restructure complete. Manual follow-up:"
echo "  1. Remove system route imports from app/api/v1/router.py."
echo "  2. Register root operational routes in app/main.py."
echo "  3. Confirm app/auth/dependencies.py imports from app/security/jwt.py."
echo "  4. RefreshTokenRepository protocol needs three distinct revocation"
echo "     methods (see docs/02-sequence-diagrams.md for full contract):"
echo "       revoke_token(token_hash)              -- logout, Flow 9"
echo "       revoke_family(family_id)               -- reuse detected, Flow 5"
echo "       revoke_all_active(user_id, tenant_id)  -- logout-all, Flow 10"
echo "     revoke_family and revoke_all_active must revoke EVERY non-revoked"
echo "     row in scope, not just the current leaf token per family."
echo
git status --short
