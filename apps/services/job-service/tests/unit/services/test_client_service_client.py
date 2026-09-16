"""
tests/unit/services/test_client_service_client.py

Uses httpx.MockTransport -- no additional test dependency needed.
Covers success parsing, error translation (404, 5xx), the retry policy
(transport failure retried once; a completed response, even a 5xx one,
never retried), and JWT forwarding.
"""

from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.exceptions.job import ClientNotFoundError, ServiceUnavailableError
from app.services.client_service_client import ClientServiceClient


def _client_payload(client_id: UUID) -> dict:
    site_id = uuid4()
    contact_id = uuid4()

    return {
        "id": str(client_id),
        "name": "Birmingham Plumbing Co.",
        "status": "active",
        "sites": [
            {
                "id": str(site_id),
                "label": "Head Office",
                "address": {
                    "line1": "10 New Street",
                    "line2": None,
                    "city": "Birmingham",
                    "postcode": "B1 1AA",
                    "country": None,
                },
            }
        ],
        "contacts": [
            {
                "id": str(contact_id),
                "name": "Alex Morgan",
                "email": None,
                "phone": "0121 555 0100",
            }
        ],
    }


async def test_get_client_returns_parsed_response_on_success() -> None:
    client_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(200, json=_client_payload(client_id))

    client = ClientServiceClient(
        base_url="http://client-service:8000",
        transport=httpx.MockTransport(handler),
    )
    result = await client.get_client(client_id, access_token="test-token")

    assert result.id == client_id
    assert result.name == "Birmingham Plumbing Co."
    assert result.status == "active"

    assert len(result.sites) == 1
    assert result.sites[0].label == "Head Office"
    assert result.sites[0].address.line2 is None
    assert result.sites[0].address.country is None

    assert len(result.contacts) == 1
    assert result.contacts[0].name == "Alex Morgan"
    assert result.contacts[0].email is None
    assert result.contacts[0].phone == "0121 555 0100"


async def test_get_client_raises_client_not_found_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = ClientServiceClient(
        base_url="http://client-service:8000",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ClientNotFoundError):
        await client.get_client(uuid4(), access_token="test-token")


async def test_get_client_raises_service_unavailable_on_5xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = ClientServiceClient(
        base_url="http://client-service:8000",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ServiceUnavailableError):
        await client.get_client(uuid4(), access_token="test-token")


async def test_get_client_retries_once_on_transport_failure_then_succeeds() -> None:
    client_id = uuid4()
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("simulated connection failure", request=request)
        return httpx.Response(200, json=_client_payload(client_id))

    client = ClientServiceClient(
        base_url="http://client-service:8000",
        transport=httpx.MockTransport(handler),
    )
    result = await client.get_client(client_id, access_token="test-token")

    assert calls["count"] == 2
    assert result.id == client_id


async def test_get_client_raises_service_unavailable_after_retry_exhausted() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ConnectError("simulated connection failure", request=request)

    client = ClientServiceClient(
        base_url="http://client-service:8000",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ServiceUnavailableError):
        await client.get_client(uuid4(), access_token="test-token")

    # Proves the promised retry actually happened -- not just that the
    # right exception eventually surfaced.
    assert calls["count"] == 2


async def test_get_client_never_retries_a_completed_5xx_response() -> None:
    """The important negative case: a 5xx is a COMPLETED response, not
    a transport failure. Amendment 7 permits retrying the latter only
    -- this proves a 5xx is called exactly once, not twice."""
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500)

    client = ClientServiceClient(
        base_url="http://client-service:8000",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ServiceUnavailableError):
        await client.get_client(uuid4(), access_token="test-token")

    assert calls["count"] == 1


async def test_get_client_rejects_missing_required_nullable_contact_field() -> None:
    """Proves the distinction the populated success test only proves
    half of: explicit null is accepted (asserted there), but omitting
    a required-but-nullable field entirely is rejected. One
    representative field is sufficient -- this isn't Pydantic edge-
    case testing, it's confirming the contract choice we deliberately
    made for this checkpoint."""
    client_id = uuid4()
    payload = _client_payload(client_id)
    del payload["contacts"][0]["email"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = ClientServiceClient(
        base_url="http://client-service:8000",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValidationError):
        await client.get_client(client_id, access_token="test-token")
