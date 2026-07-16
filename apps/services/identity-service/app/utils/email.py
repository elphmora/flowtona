"""
app/utils/email.py

Email normalization — added 2026-07-14 while writing the first repository
implementation, to prevent "Dana@Example.com" and "dana@example.com"
being treated as different users.

Deliberately simple: lowercase and strip whitespace. Not full RFC 5321
normalization (which technically permits the local part to be
case-sensitive) — in practice essentially every real-world mail provider
treats addresses case-insensitively, and matching that common behavior
is more useful here than technical correctness nobody relies on.
"""


def normalise_email(email: str) -> str:
    return email.strip().lower()
