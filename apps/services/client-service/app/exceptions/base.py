"""
app/exceptions/base.py

Base class for client-service's domain exception hierarchy — mirrors
identity-service's DomainError contract exactly: subclasses carry
code/status_code/title as class attributes and a detail message set
via __init__. Translated into RFC 9457 Problem Details by
app/api/errors.py (not built yet — this exists ahead of it since
services need something to raise before routes exist to catch it).
"""


class DomainError(Exception):
    code: str
    status_code: int
    title: str

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)
