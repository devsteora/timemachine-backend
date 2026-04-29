"""
Admin CSV import for users. Expected columns (header row, case-insensitive):

  Required: email, password
  Optional: name, role, team, manager_email

  - role: ADMIN | MANAGER | EMPLOYEE (default EMPLOYEE)
  - team: one of TeamCode (DEV, QC, AV, ...) or empty
  - manager_email: must match an existing user or another row in the same file
    (resolved after all rows are inserted; see manager_warnings on partial misses)
"""

from __future__ import annotations

import logging
import csv
import io
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import TypeAdapter, EmailStr
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.models.user import User
from app.schemas.schemas import CsvUserImportResult, CsvUserImportRowError, TeamCode

log = logging.getLogger(__name__)

BCRYPT_MAX_PASSWORD_BYTES = 72
_ROLES: Set[str] = {"ADMIN", "MANAGER", "EMPLOYEE"}
_TeamValues: Set[str] = {e.value for e in TeamCode}
_email_adapter = TypeAdapter(EmailStr)


def _validate_row(
    row: Dict[str, str],
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    email_raw = (row.get("email") or "").strip()
    if not email_raw:
        return None, "email is required"
    try:
        email = str(_email_adapter.validate_python(email_raw))
    except Exception:
        return None, "invalid email"

    password = row.get("password")
    if password is None or not str(password).strip():
        return None, "password is required"
    password_s = str(password)
    if len(password_s.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        return None, f"password exceeds {BCRYPT_MAX_PASSWORD_BYTES} bytes (bcrypt limit)"

    role_raw = (row.get("role") or "EMPLOYEE").strip().upper() or "EMPLOYEE"
    if role_raw not in _ROLES:
        return None, f"invalid role {role_raw!r}; use ADMIN, MANAGER, or EMPLOYEE"

    team_raw = (row.get("team") or "").strip() or None
    if team_raw and team_raw not in _TeamValues:
        return None, (
            f"invalid team {team_raw!r}; use one of: {', '.join(sorted(_TeamValues))}"
        )

    name = (row.get("name") or "").strip() or None

    manager_email_raw = (row.get("manager_email") or "").strip() or None
    if manager_email_raw:
        try:
            manager_email = str(
                _email_adapter.validate_python(manager_email_raw)
            )
        except Exception:
            return None, "invalid manager_email"
    else:
        manager_email = None

    if manager_email and manager_email == email:
        return None, "manager_email must differ from the user's own email"

    return {
        "email": email,
        "password": password_s,
        "role": role_raw,
        "team": team_raw,
        "name": name,
        "manager_email": manager_email,
    }, None


def import_users_from_csv_bytes(
    db: Session,
    file_bytes: bytes,
) -> CsvUserImportResult:
    errors: List[CsvUserImportRowError] = []
    manager_warnings: List[CsvUserImportRowError] = []

    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return CsvUserImportResult(
            created=0,
            failed=1,
            errors=[
                CsvUserImportRowError(
                    row_number=0,
                    detail="File must be UTF-8 encoded (with or without BOM).",
                )
            ],
        )

    sio = io.StringIO(text)
    raw_rows = list(csv.reader(sio))
    if not raw_rows:
        return CsvUserImportResult(
            created=0,
            failed=0,
            errors=[],
        )

    header = [c.strip().lower() for c in raw_rows[0]]
    if "email" not in header or "password" not in header:
        return CsvUserImportResult(
            created=0,
            failed=1,
            errors=[
                CsvUserImportRowError(
                    row_number=1,
                    detail="Header must include: email, password. Optional: name, role, team, manager_email.",
                )
            ],
        )

    data_rows: List[Tuple[int, Dict[str, str]]] = []
    for line_i, values in enumerate(raw_rows[1:], start=2):
        row: Dict[str, str] = {}
        padding = (list(values) + [""] * len(header))[: len(header)]
        for h, v in zip(header, padding):
            row[h] = (v or "").strip()
        if not any((row.get("email") or "").strip(), (row.get("password") or "").strip()):
            continue
        data_rows.append((line_i, row))

    email_counts: dict[str, int] = {}
    for _ln, r in data_rows:
        e = (r.get("email") or "").lower()
        if e:
            email_counts[e] = email_counts.get(e, 0) + 1

    to_create: List[Tuple[int, Dict[str, Any]]] = []
    for line_i, row in data_rows:
        if not (row.get("email") or "").strip():
            errors.append(
                CsvUserImportRowError(
                    row_number=line_i, detail="email is required"
                )
            )
            continue
        em = (row.get("email") or "").lower()
        if email_counts.get(em, 0) > 1:
            errors.append(
                CsvUserImportRowError(
                    row_number=line_i,
                    email=row.get("email"),
                    detail="duplicate email in this CSV (each address must appear once).",
                )
            )
            continue
        data, err = _validate_row(row)
        if err:
            errors.append(
                CsvUserImportRowError(
                    row_number=line_i,
                    email=row.get("email"),
                    detail=err,
                )
            )
            continue
        assert data is not None
        data["email"] = str(data["email"]).strip().lower()
        if data.get("manager_email"):
            data["manager_email"] = str(data["manager_email"]).strip().lower()
        to_create.append((line_i, data))

    created = 0
    pending_managers: List[Tuple[int, str, str]] = []  # line, user_email, manager_email

    for line_i, data in to_create:
        existing = (
            db.query(User)
            .filter(func.lower(User.email) == data["email"])
            .first()
        )
        if existing:
            errors.append(
                CsvUserImportRowError(
                    row_number=line_i,
                    email=data["email"],
                    detail="email is already registered",
                )
            )
            continue

        uid = str(uuid.uuid4())
        user = User(
            id=uid,
            email=data["email"],
            hashed_password=get_password_hash(data["password"]),
            name=data["name"],
            role=data["role"],
            team=data["team"],
            manager_id=None,
        )
        db.add(user)
        created += 1
        if data.get("manager_email"):
            pending_managers.append(
                (line_i, data["email"], data["manager_email"])
            )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        log.warning("CSV import user insert failed: %s", exc)
        detail = str(exc.orig) if getattr(exc, "orig", None) else str(exc)
        return CsvUserImportResult(
            created=0,
            failed=len(to_create),
            errors=[
                CsvUserImportRowError(
                    row_number=0,
                    detail=f"Database rejected the batch (usually duplicate email): {detail}",
                )
            ],
            manager_warnings=[],
        )

    for line_i, user_email, manager_email in pending_managers:
        user = db.query(User).filter(func.lower(User.email) == user_email).first()
        if not user:
            continue
        mgr = db.query(User).filter(func.lower(User.email) == manager_email).first()
        if not mgr:
            manager_warnings.append(
                CsvUserImportRowError(
                    row_number=line_i,
                    email=user_email,
                    detail=f"manager_email {manager_email!r} not found; user was created without a manager",
                )
            )
            continue
        if mgr.id == user.id:
            manager_warnings.append(
                CsvUserImportRowError(
                    row_number=line_i,
                    email=user_email,
                    detail="manager cannot be self; skipped",
                )
            )
            continue
        user.manager_id = mgr.id
        db.add(user)
    if pending_managers:
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            log.warning("CSV import manager link failed: %s", exc)
            detail = str(exc.orig) if getattr(exc, "orig", None) else str(exc)
            manager_warnings.append(
                CsvUserImportRowError(
                    row_number=0,
                    email=None,
                    detail=f"Could not save manager links: {detail}",
                )
            )

    return CsvUserImportResult(
        created=created,
        failed=len(errors),
        errors=errors,
        manager_warnings=manager_warnings,
    )
