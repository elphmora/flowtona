"""
app/constants/permissions.py

client-service's own permission string constants — the literal strings
this service checks for in a verified token's permissions claim.
Deliberately NOT imported from identity-service (Platform Conventions
§12): identity-service owns resolving WHO gets which permissions;
client-service only needs to know the exact strings it checks for. A
typo like "client:read" would otherwise be syntactically valid and
silently deny every request — these constants exist so that mistake
becomes a NameError/ImportError at import time instead.
"""

from typing import Literal

ClientPermission = Literal["clients:read", "clients:write"]

CLIENTS_READ: ClientPermission = "clients:read"
CLIENTS_WRITE: ClientPermission = "clients:write"
