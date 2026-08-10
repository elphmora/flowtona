"""
tests/unit/middleware/test_middleware_ordering.py

Locks in the configured middleware registration sequence as an
explicit, tested decision — not because one order is proven "correct"
(neither middleware currently depends on the other's side effects),
but because a future accidental change to add_request_id_middleware()/
add_metrics_middleware() call order (here, or eventually in main.py)
should be a visible, deliberate test failure, not a silent
configuration change nobody notices until a THIRD middleware (e.g.
structured logging) is added that actually depends on this ordering.

Tests the registration CONFIGURATION exposed through app.user_middleware
— NOT runtime execution order. Those are related but distinct claims:
Starlette builds the effective call chain by wrapping the application
around this list, which is framework behavior this test doesn't
observe directly.

app.user_middleware lists the most-recently-added middleware first,
not in raw insertion order — conftest.py registers RequestIDMiddleware
before MetricsMiddleware, so the real list order is
['MetricsMiddleware', 'RequestIDMiddleware'].
"""

from typing import cast

from tests.unit.middleware.conftest import _build_test_app


def test_metrics_appears_before_request_id_in_user_middleware_list() -> None:
    """Named for app.user_middleware's actual LIST order (Metrics
    first), not conftest.py's CALL order (RequestID registered first)
    — see module docstring."""
    app = _build_test_app()

    # Starlette types Middleware.cls as _MiddlewareFactory[P], though
    # this fixture only ever registers concrete middleware classes —
    # cast to `type` so mypy recognizes .__name__.
    middleware_names = [cast(type, entry.cls).__name__ for entry in app.user_middleware]

    assert middleware_names.index("MetricsMiddleware") < middleware_names.index(
        "RequestIDMiddleware"
    )
