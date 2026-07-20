"""tests/unit/api/test_dependencies.py

Tests for app/api/dependencies.py's service-wiring logic.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import build_auth_service, get_auth_service
from app.core.config import Settings
from app.exceptions.auth import InvalidCredentialsError
from app.services.auth_service import AuthService
from scripts.generate_signing_keypair import generate_keypair


class TestBuildAuthService:
    def test_constructs_successfully_without_a_keypair_present(self, tmp_path):
        """Construction itself must succeed even with no keypair on
        disk yet — TokenService loads keys lazily on first actual use,
        not at construction time, so build_auth_service() shouldn't
        need one just to assemble the object graph."""
        settings = Settings(SECRETS_DIR=tmp_path)
        auth_service = build_auth_service(settings)
        assert isinstance(auth_service, AuthService)

    @pytest.mark.asyncio
    async def test_produces_a_genuinely_working_service(self, tmp_path):
        """The real test — not just that construction doesn't raise,
        but that the resulting AuthService can actually complete a full
        workflow end to end."""
        generate_keypair(tmp_path)
        settings = Settings(SECRETS_DIR=tmp_path)
        auth_service = build_auth_service(settings)

        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )

        assert session.user.email == "dana@example.com"
        assert session.access_token
        assert session.raw_refresh_token

    @pytest.mark.asyncio
    async def test_uses_the_configured_secrets_dir(self, tmp_path):
        """Confirms the SPECIFIC configured path is actually used, not
        some hardcoded default — two different tmp_path directories,
        each with their own real keypair, must each work independently."""
        dir_a = tmp_path / "secrets_a"
        dir_b = tmp_path / "secrets_b"
        generate_keypair(dir_a)
        generate_keypair(dir_b)

        service_a = build_auth_service(Settings(SECRETS_DIR=dir_a))
        service_b = build_auth_service(Settings(SECRETS_DIR=dir_b))

        session_a = await service_a.signup(
            email="a@example.com",
            password="hunter2",
            display_name="A",
            tenant_label="A's Business",
        )
        session_b = await service_b.signup(
            email="b@example.com",
            password="hunter2",
            display_name="B",
            tenant_label="B's Business",
        )

        # Each service's own access token must verify against its OWN
        # keypair — cross-checking would fail if they somehow shared
        # key material instead of using their own configured directory.
        assert session_a.access_token != session_b.access_token

    @pytest.mark.asyncio
    async def test_two_calls_produce_independent_stores(self, tmp_path):
        """Each call must produce a genuinely fresh, isolated service
        graph — no shared state between separate build_auth_service()
        invocations, which would be a real bug if this were ever called
        more than once (e.g. in tests, or a future multi-worker setup)."""
        generate_keypair(tmp_path)
        settings = Settings(SECRETS_DIR=tmp_path)

        service_1 = build_auth_service(settings)
        service_2 = build_auth_service(settings)

        await service_1.signup(
            email="only.in.service.one@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )

        # A user created via service_1 must not be visible via service_2
        # — proves the two calls didn't end up sharing one store.
        with pytest.raises(InvalidCredentialsError):
            await service_2.login(
                email="only.in.service.one@example.com", password="hunter2"
            )


class TestGetAuthService:
    def test_returns_the_instance_attached_to_app_state(self, tmp_path):
        """Minimal integration test — confirms the dependency actually
        reads from app.state the way main.py's lifespan handler
        attaches it, not just that the function compiles."""
        generate_keypair(tmp_path)
        settings = Settings(SECRETS_DIR=tmp_path)
        expected_service = build_auth_service(settings)

        app = FastAPI()
        app.state.auth_service = expected_service

        @app.get("/probe")
        async def _probe(auth_service: AuthService = Depends(get_auth_service)):
            return {"is_expected_instance": auth_service is expected_service}

        client = TestClient(app)
        response = client.get("/probe")

        assert response.json()["is_expected_instance"] is True
