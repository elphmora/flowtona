"""
app/services/logging_email_sender.py

Local-development-only placeholder for AuthEmailSender — logs instead
of sending, so the app can run before a real email provider exists.
Replace before any real deployment.
"""

import logging

from app.models.tenant import Tenant
from app.models.user import User

logger = logging.getLogger(__name__)


class LoggingEmailSender:
    async def send_verification_email(self, *, to: str, raw_token: str) -> None:
        logger.info(
            "Would send verification email to %s (token starts with %s...)",
            to,
            raw_token[:8],
        )

    async def send_invitation_email(
        self, *, to: str, raw_token: str, tenant: Tenant, invited_by: User
    ) -> None:
        logger.info(
            "Would send invitation email to %s for tenant %s, invited by %s "
            "(token starts with %s...)",
            to,
            tenant.tenant_label,
            invited_by.email,
            raw_token[:8],
        )
