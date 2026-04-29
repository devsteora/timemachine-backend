"""
Selectable reporting managers for mail compose.

Replace or extend this list with DB/config later; keep name + email in sync with HR records.
"""

from __future__ import annotations

from typing import TypedDict


class ManagerRecord(TypedDict):
    name: str
    email: str


# Canonical reporting-manager roster (mail compose + admin assignment). Edit here only.
MANAGER_DIRECTORY: list[ManagerRecord] = [
    {"name": "Sayan Chatterjee", "email": "sayanc@steorasystems.com"},
    {"name": "Sanchita Chattopadhyay", "email": "sanchitac@steorasystems.com"},
    {"name": "Trideb Halder", "email": "tridebhalder@steorasystems.com"},
    {"name": "Pranay Chhetri", "email": "pchhetri@steorasystems.com"},
    {"name": "Raj Nandini Saha", "email": "rnsaha@steorasystems.com"},
    {"name": "Debraj Tarafder", "email": "dtarafder@steorasystems.com"},
]


def directory_emails_lowercase() -> set[str]:
    return {m["email"].strip().lower() for m in MANAGER_DIRECTORY}


def is_email_in_directory(email: str) -> bool:
    return email.strip().lower() in directory_emails_lowercase()
