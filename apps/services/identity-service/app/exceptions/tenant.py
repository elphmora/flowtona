"""
app/exceptions/tenant.py

Domain exceptions for tenant-related business rules (Decision 8).
"""

from app.exceptions.base import DomainError


class InvalidTenantLabelError(DomainError):
    code = "invalid_tenant_label"
    status_code = 422
    title = "Invalid tenant label"

    def __init__(self) -> None:
        super().__init__("Tenant label must not be empty.")
