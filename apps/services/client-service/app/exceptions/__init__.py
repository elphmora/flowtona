"""
app/exceptions/__init__.py
"""

from app.exceptions.base import DomainError
from app.exceptions.client import (
    ArchiveViaUpdateNotAllowedError,
    ClientArchivedError,
    ClientNotFoundError,
)
from app.exceptions.contact import ContactNotFoundError
from app.exceptions.site import SiteNotFoundError

__all__ = [
    "ArchiveViaUpdateNotAllowedError",
    "ClientArchivedError",
    "ClientNotFoundError",
    "ContactNotFoundError",
    "DomainError",
    "SiteNotFoundError",
]
