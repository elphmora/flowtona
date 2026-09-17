"""
tests/contract/test_client_service_contract.py

Answers one narrow question: does the real Client Service response
still satisfy the exact wire shape ClientServiceResponse (Job
Service's own consumer contract) requires? Deliberately different from
tests/unit/services/test_client_service_client.py's httpx.MockTransport
tests -- those prove ClientServiceClient's HTTP mechanics behave
correctly given a response shape WE constructed. This test prevents
the classic distributed-system failure where Client Service changes
something (a field name, a nesting level, a required/nullable flip)
and a mock keeps happily reproducing the old, now-stale assumption.

REQUIRES A REAL, RUNNING CLIENT SERVICE. Skipped entirely unless both
environment variables below are set.

  JOB_SERVICE_CONTRACT_TEST_CLIENT_SERVICE_URL
      Base URL of a real, running client-service.
  JOB_SERVICE_CONTRACT_TEST_ACCESS_TOKEN
      A valid bearer token with BOTH clients:write and clients:read --
      this test self-provisions its own fixture client/site/contact
      via real POST calls (needs clients:write), then reads it back
      (needs clients:read).

Self-provisioning, using request shapes confirmed directly against
client-service's real source (app/models/enums.py,
app/api/schemas/{client,site,address,contact}.py) -- not guessed.
Fixture client name includes a random suffix (not a fixed string) --
nothing in the confirmed schema indicates name uniqueness is enforced,
but there's no reason for this test to depend on that remaining true.
The contact is associated with the created site via site_id -- makes
the fixture internally realistic (client -> site -> contact actually
linked), not three merely co-located resources.

Deliberately separates two different claims: does the real PROVIDER's
response, taken as raw JSON via a plain httpx.AsyncClient (not through
ClientServiceClient, which would parse it immediately and hide this
step), satisfy Job Service's CONSUMER contract
(ClientServiceResponse.model_validate(...), the exact model production
code uses)? ClientServiceClient's own HTTP mechanics (timeout, retry,
error translation) stay exactly where they already are -- proven in
tests/unit/services/test_client_service_client.py -- not re-tested,
and not re-mocked, here.

status is asserted only as a non-empty string, not against the full
confirmed {"active", "inactive", "archived"} vocabulary (even though
that vocabulary IS confirmed, in app/models/enums.py) -- this contract
test's job is to verify what JOB SERVICE actually consumes (a string
it can compare against "archived"), not to make itself responsible for
asserting Client Service's entire status vocabulary.

No 404-translation test here -- ClientServiceClient's 404 ->
ClientNotFoundError behavior is already thoroughly proven in
tests/unit/services/test_client_service_client.py. Hitting a real
provider to re-confirm a 404 shows up isn't the contract-drift risk
this checkpoint exists to guard against.

Cleanup via try/finally, in dependency order (contact, then site, then
client) -- client-service's real DELETE endpoints, confirmed shapes.
All three DELETE routes (archive_client, delete_site, delete_contact)
use require_permission(CLIENTS_WRITE), confirmed directly against
client-service's real app/api/v1/{clients,sites,contacts}.py source --
the already-documented clients:write + clients:read token requirement
above is complete; cleanup needs no additional permission.

Cleanup in dependency order for whatever fixture resources were
successfully created before the test completed or failed -- not
genuine best-effort cleanup (a transport exception on the first DELETE
would prevent the later ones from running, and a cleanup-time
exception could mask the original assertion failure). Acceptable for
this Phase 1 checkpoint against an in-memory, disposable provider;
worth building real best-effort cleanup later if persistent test
environments make the current gap costly enough to matter.

Note client DELETE archives (soft), it does not hard-delete -- the
fixture client record remains, archived, after this test runs. That's
acceptable (the point of cleanup here is not leaving live, non-archived
clutter), and another reason the fixture name includes a random suffix
rather than a fixed one.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.services.client_service_client import ClientServiceResponse

_BASE_URL = os.environ.get("JOB_SERVICE_CONTRACT_TEST_CLIENT_SERVICE_URL")
_ACCESS_TOKEN = os.environ.get("JOB_SERVICE_CONTRACT_TEST_ACCESS_TOKEN")

_SKIP_REASON = (
    "Contract test requires a real, running Client Service. Set "
    "JOB_SERVICE_CONTRACT_TEST_CLIENT_SERVICE_URL and "
    "JOB_SERVICE_CONTRACT_TEST_ACCESS_TOKEN (a valid bearer token with "
    "BOTH clients:write and clients:read -- this test self-provisions "
    "its own fixture data) to run it."
)

_CONFIGURED = bool(_BASE_URL and _ACCESS_TOKEN)


@pytest.mark.skipif(not _CONFIGURED, reason=_SKIP_REASON)
async def test_client_service_response_matches_consumed_contract() -> None:
    assert _BASE_URL is not None and _ACCESS_TOKEN is not None
    headers = {"Authorization": f"Bearer {_ACCESS_TOKEN}"}
    fixture_suffix = uuid4().hex[:8]
    client_name = f"job-service-contract-{fixture_suffix}"

    client_id: UUID | None = None
    site_id: UUID | None = None
    contact_id: UUID | None = None

    async with httpx.AsyncClient(base_url=_BASE_URL, timeout=5.0) as http:
        try:
            # ---- Arrange: real POSTs, confirmed real request shapes ----
            client_resp = await http.post(
                "/v1/clients",
                json={"name": client_name, "client_type": "commercial"},
                headers=headers,
            )
            assert client_resp.status_code == 201, client_resp.text
            client_id = UUID(client_resp.json()["id"])

            site_resp = await http.post(
                f"/v1/clients/{client_id}/sites",
                json={
                    "label": "Contract Test Site",
                    "address": {
                        "line1": "1 Test Street",
                        "city": "Testville",
                        "postcode": "T1 1AA",
                    },
                },
                headers=headers,
            )
            assert site_resp.status_code == 201, site_resp.text
            site_id = UUID(site_resp.json()["id"])

            contact_resp = await http.post(
                f"/v1/clients/{client_id}/contacts",
                json={
                    "name": "Contract Test Contact",
                    "email": "contract-test@example.com",
                    "site_id": str(site_id),
                },
                headers=headers,
            )
            assert contact_resp.status_code == 201, contact_resp.text
            contact_id = UUID(contact_resp.json()["id"])

            # ---- The actual contract boundary: raw JSON from the real provider ----
            get_resp = await http.get(f"/v1/clients/{client_id}", headers=headers)
            assert get_resp.status_code == 200, get_resp.text
            raw_payload: dict[str, Any] = get_resp.json()

            # ---- Job Service's consumer contract: does the real payload parse? ----
            response = ClientServiceResponse.model_validate(raw_payload)

            assert response.id == client_id
            assert response.name == client_name
            assert isinstance(response.status, str) and response.status

            matching_sites = [s for s in response.sites if s.id == site_id]
            assert len(matching_sites) == 1, (
                "Created site not found in the client's sites array"
            )
            site = matching_sites[0]
            assert site.label == "Contract Test Site"
            assert site.address.line1 == "1 Test Street"
            assert site.address.city == "Testville"
            assert site.address.postcode == "T1 1AA"
            assert site.address.line2 is None
            assert site.address.country is None

            matching_contacts = [c for c in response.contacts if c.id == contact_id]
            assert len(matching_contacts) == 1, (
                "Created contact not found in the client's contacts array"
            )
            contact = matching_contacts[0]
            assert contact.name == "Contract Test Contact"
            assert contact.email == "contract-test@example.com"
            assert contact.phone is None

        finally:
            # Cleanup in dependency order for whatever fixture resources
            # were successfully created before the test completed or
            # failed.
            if contact_id is not None:
                await http.delete(
                    f"/v1/clients/{client_id}/contacts/{contact_id}", headers=headers
                )
            if site_id is not None:
                await http.delete(
                    f"/v1/clients/{client_id}/sites/{site_id}", headers=headers
                )
            if client_id is not None:
                await http.delete(f"/v1/clients/{client_id}", headers=headers)
