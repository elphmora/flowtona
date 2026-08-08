"""
app/repositories/__init__.py
"""

from app.repositories.client_repository import ClientPage, ClientRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.exceptions import (
    ConcurrentUpdateError,
    DuplicateEntryError,
    ImmutableFieldError,
    RecordArchivedError,
    RecordNotFoundError,
)
from app.repositories.site_repository import SiteRepository

__all__ = [
    "ClientPage",
    "ClientRepository",
    "ConcurrentUpdateError",
    "ContactRepository",
    "DuplicateEntryError",
    "ImmutableFieldError",
    "RecordArchivedError",
    "RecordNotFoundError",
    "SiteRepository",
]
