"""
tests/integration/test_main.py

Verifies app ASSEMBLY itself -- that create_app() wires lifespan
correctly and that both the settings and registry injection seams
actually work -- not individual route behavior (that's
tests/unit/api/system/'s job).
"""

from fastapi.testclient import TestClient

from app.api.dependencies import ServiceRegistry, build_services
from app.core.config import Settings
from app.main import create_app


def test_default_registry_and_settings_are_populated_via_lifespan() -> None:
    app = create_app()
    with TestClient(app):
        assert isinstance(app.state.services, ServiceRegistry)
        assert isinstance(app.state.settings, Settings)


def test_injected_registry_is_used_instead_of_default() -> None:
    # build_services() now requires settings -- a real call-site
    # regression from this checkpoint's signature change (Settings()
    # needed to construct ClientServiceClient), caught by this
    # pre-existing test, not something to silently work around.
    injected = build_services(Settings())
    app = create_app(registry=injected)
    with TestClient(app):
        assert app.state.services is injected


def test_supplied_settings_are_used_instead_of_default() -> None:
    custom_settings = Settings(SERVICE_NAME="test-job-service")
    app = create_app(settings=custom_settings)
    with TestClient(app):
        assert app.state.settings is custom_settings


def test_app_state_not_populated_without_context_manager() -> None:
    """Documents the exact footgun app/main.py's docstring warns
    about: bare TestClient(app) never runs lifespan."""
    app = create_app()
    TestClient(app)  # bare, deliberately not used as a context manager
    assert not hasattr(app.state, "services")
    assert not hasattr(app.state, "settings")
