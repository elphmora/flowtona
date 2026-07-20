"""tests/unit/test_config.py

Tests for app/core/config.py's startup-time validation.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


class TestErrorBaseUriValidation:
    def test_default_value_is_valid(self, monkeypatch):
        """Settings() reads .env and process environment variables by
        default — if either happens to define ERROR_BASE_URI on a
        given machine, this test would silently check THAT value
        instead of the actual declared field default. Isolated
        explicitly rather than relying on a clean environment."""
        monkeypatch.delenv("ERROR_BASE_URI", raising=False)
        settings = Settings(_env_file=None)
        assert settings.ERROR_BASE_URI == "https://flowtona.dev/errors"

    def test_rejects_missing_scheme(self):
        with pytest.raises(ValidationError):
            Settings(ERROR_BASE_URI="flowtona.dev/errors")

    def test_rejects_trailing_slash(self):
        with pytest.raises(ValidationError):
            Settings(ERROR_BASE_URI="https://flowtona.dev/errors/")

    def test_accepts_valid_custom_value(self):
        settings = Settings(ERROR_BASE_URI="https://staging.flowtona.dev/errors")
        assert settings.ERROR_BASE_URI == "https://staging.flowtona.dev/errors"

    def test_accepts_http_scheme(self):
        """http:// (not just https://) is valid — useful for local/
        internal deployments that don't terminate TLS at this layer."""
        settings = Settings(ERROR_BASE_URI="http://localhost:8000/errors")
        assert settings.ERROR_BASE_URI == "http://localhost:8000/errors"

    @pytest.mark.parametrize(
        "value",
        [
            "https://",  # scheme + nothing else - no host
            "https:///errors",  # empty host, path only
            " https://flowtona.dev/errors",  # leading whitespace
            "https://flowtona.dev/errors?version=1",  # query string
            "https://flowtona.dev/errors#section",  # fragment
            "https://user:password@flowtona.dev/errors",  # embedded credentials
            "https://flowtona.dev",  # no path at all
            "https://flowtona.dev/",  # root path only
        ],
    )
    def test_rejects_malformed_values(self, value):
        """These would all pass a naive prefix-and-trailing-slash-only
        check — proves the validator is structurally checking the URL
        (via urlsplit), not just pattern-matching its start and end."""
        with pytest.raises(ValidationError):
            Settings(ERROR_BASE_URI=value)
