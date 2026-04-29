"""
Selectable reporting managers for mail compose.

Replace or extend this list with DB/config later; keep name + email in sync with HR records.
"""

from __future__ import annotations

from typing import TypedDict


class ManagerRecord(TypedDict):
    name: str
    email: str


# Five managers — add entries here as the organization grows.
MANAGER_DIRECTORY: list[ManagerRecord] = [
    {"name": "Alex Rivera", "email": "alex.rivera@managers.example.com"},
    {"name": "Jordan Lee", "email": "jordan.lee@managers.example.com"},
    {"name": "Sam Patel", "email": "sam.patel@managers.example.com"},
    {"name": "Taylor Morgan", "email": "taylor.morgan@managers.example.com"},
    {"name": "Casey Nguyen", "email": "casey.nguyen@managers.example.com"},
]


def directory_emails_lowercase() -> set[str]:
    return {m["email"].strip().lower() for m in MANAGER_DIRECTORY}


def is_email_in_directory(email: str) -> bool:
    return email.strip().lower() in directory_emails_lowercase()
