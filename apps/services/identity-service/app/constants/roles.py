"""
app/constants/roles.py

Fixed roles per Decision 5 — not tenant-customizable in Phase 1.
"""

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    DISPATCHER = "dispatcher"
    TECHNICIAN = "technician"
