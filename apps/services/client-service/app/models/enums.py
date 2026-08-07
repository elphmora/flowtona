"""
app/models/enums.py

Enumerations for client-service domain entities.

See client-service-architecture.md Decision 4 (data model) and
Decision 5 (client lifecycle) for the reasoning behind each enum.
"""

from __future__ import annotations

from enum import Enum


class ClientType(str, Enum):
    """Client.client_type — Decision 4."""

    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"


class ClientStatus(str, Enum):
    """Client.status — Decision 5.

    active <-> inactive is freely editable via PATCH in either direction.
    archived is a terminal, fully immutable state reached only via
    DELETE. No code path transitions archived -> active in Phase 1 — no
    restore workflow exists yet (see ADR Deferred Decisions).
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"
