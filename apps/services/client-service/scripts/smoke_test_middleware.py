"""
scripts/smoke_test_middleware.py

Manual smoke test for app/middleware/request_id.py and
app/middleware/metrics.py — not a pytest file, run directly:

    python scripts/smoke_test_middleware.py

Confirms the seven behaviors the design depends on before they're
trusted as "verified" rather than "derived from documented Starlette
architecture." Delete or convert into real pytest tests
(tests/unit/middleware/) once confirmed.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.metrics import (
    REQUEST_COUNT,
    REQUEST_LATENCY_SECONDS,
    add_metrics_middleware,
)
from app.middleware.request_id import add_request_id_middleware

app = FastAPI()

add_request_id_middleware(app)
add_metrics_middleware(app)


@app.get("/v1/clients/{client_id}")
async def get_client(client_id: str):
    return {"client_id": client_id}


@app.get("/v1/broken")
async def broken():
    raise RuntimeError("deliberate failure")


client = TestClient(app, raise_server_exceptions=False)


# 1. Two resolved IDs must collapse onto one route-template label.
client.get("/v1/clients/aaa")
client.get("/v1/clients/bbb")


# 2. Arbitrary unmatched paths must collapse onto one sentinel.
client.get("/nope/1")
client.get("/nope/2")


# 3. Generated request ID.
r1 = client.get("/v1/clients/ccc")
generated_id = r1.headers.get("x-request-id")
print("generated X-Request-ID present:", bool(generated_id))
print("generated X-Request-ID:", generated_id)


# 4. Valid inbound request ID should be propagated unchanged.
r2 = client.get(
    "/v1/clients/ddd",
    headers={"X-Request-ID": "flowtona-test-123"},
)
print(
    "valid inbound ID propagated:",
    r2.headers.get("x-request-id") == "flowtona-test-123",
)


# 5. Oversized inbound ID should be rejected/replaced.
oversized = "a" * 500
r3 = client.get(
    "/v1/clients/eee",
    headers={"X-Request-ID": oversized},
)
returned_id = r3.headers.get("x-request-id")
print(
    "oversized ID replaced:",
    returned_id is not None and returned_id != oversized,
)


# 6. Exactly one outgoing X-Request-ID header.
request_id_headers = [
    (name, value)
    for name, value in r3.headers.raw
    if name.lower() == b"x-request-id"
]
print(
    "exactly one X-Request-ID response header:",
    len(request_id_headers) == 1,
)


# 7. Generic uncaught exception boundary.
r4 = client.get("/v1/broken")
print("broken route status:", r4.status_code, "(expected: 500)")
print(
    "broken route has X-Request-ID:",
    "x-request-id" in r4.headers,
    "(expected: False)",
)


print()
print("--- REQUEST_COUNT ---")
for sample in REQUEST_COUNT.collect()[0].samples:
    if sample.name.endswith("_total"):
        print(sample.labels, sample.value)


print()
print("--- LATENCY COUNTS ---")
for sample in REQUEST_LATENCY_SECONDS.collect()[0].samples:
    if sample.name.endswith("_count"):
        print(sample.labels, sample.value)