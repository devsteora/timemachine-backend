from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_current_user
from app.core.manager_directory import MANAGER_DIRECTORY, is_email_in_directory
from app.models.user import User
from app.schemas.schemas import (
    MailComposeContextResponse,
    MailSendRequest,
    MailSendResponse,
    ManagerDirectoryEntry,
    ReportingManagerResponse,
)
from app.services.mail_service import is_smtp_configured, send_plain_email

router = APIRouter()


def _compose_manager_list(db: Session, user: User) -> list[ManagerDirectoryEntry]:
    """Five directory managers plus the DB-assigned manager if their email is not in the list."""
    rows: list[ManagerDirectoryEntry] = [
        ManagerDirectoryEntry(**m) for m in MANAGER_DIRECTORY
    ]
    emails = {r.email.strip().lower() for r in rows}
    if user.manager_id:
        mgr = db.query(User).filter(User.id == user.manager_id).first()
        if mgr and mgr.email.strip().lower() not in emails:
            local = mgr.email.split("@")[0]
            label = local.replace(".", " ").replace("_", " ").title()
            rows.append(
                ManagerDirectoryEntry(name=f"{label} (assigned)", email=mgr.email)
            )
    return rows


@router.get("/compose-context", response_model=MailComposeContextResponse)
def get_mail_compose_context(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assigned: str | None = None
    if current_user.manager_id:
        mgr = db.query(User).filter(User.id == current_user.manager_id).first()
        if mgr:
            assigned = mgr.email
    managers = _compose_manager_list(db, current_user)
    return MailComposeContextResponse(
        managers=managers,
        assigned_manager_email=assigned,
    )


@router.get("/reporting-manager", response_model=ReportingManagerResponse)
def get_reporting_manager(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.manager_id:
        return ReportingManagerResponse(email=None, manager_user_id=None)
    mgr = db.query(User).filter(User.id == current_user.manager_id).first()
    if not mgr:
        return ReportingManagerResponse(email=None, manager_user_id=None)
    return ReportingManagerResponse(email=mgr.email, manager_user_id=mgr.id)


def _recipient_allowed(*, db: Session, user: User, recipient_email: str) -> bool:
    r = recipient_email.strip().lower()
    if is_email_in_directory(recipient_email):
        return True
    if user.manager_id:
        mgr = db.query(User).filter(User.id == user.manager_id).first()
        if mgr and mgr.email.strip().lower() == r:
            return True
    return False


@router.post("/send-to-manager", response_model=MailSendResponse)
def send_mail_to_manager(
    payload: MailSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _recipient_allowed(
        db=db, user=current_user, recipient_email=payload.recipient_email
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a valid manager from the directory or your assigned reporting manager.",
        )

    if not is_smtp_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email sending is not configured on the server. Set SMTP_HOST, SMTP_FROM_EMAIL, and SMTP credentials.",
        )

    to_email = payload.recipient_email.strip()

    prefix = "[Enterprise Tracker] "
    subject = payload.subject.strip()
    if not subject.lower().startswith(prefix.lower()):
        subject = prefix + subject

    body = payload.body.strip()
    body = f"From: {current_user.email}\n\n{body}"

    try:
        send_plain_email(
            to_email=to_email,
            subject=subject,
            body=body,
            reply_to=current_user.email,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to send email: {e!s}",
        )

    return MailSendResponse(ok=True, sent_to=to_email)
