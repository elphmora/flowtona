"""
app/exceptions/site.py

Domain exceptions raised by SiteService — 01-api-contract.md's error
catalog for the Site subresource.
"""

from app.exceptions.base import DomainError


class SiteNotFoundError(DomainError):
    code = "site_not_found"
    status_code = 404
    title = "Site not found"

    def __init__(self) -> None:
        super().__init__("No site exists with this ID under this client.")
