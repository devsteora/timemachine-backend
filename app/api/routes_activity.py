from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import Date, and_, case, cast, distinct, func
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_current_admin, get_db
from app.models.activity import ActivityLog
from app.models.user import User
from app.core.manager_directory import MANAGER_DIRECTORY, is_email_in_directory
from app.schemas.schemas import (
    ActivityTimelineItem,
    ActivityTimelineResponse,
    AdminUserRow,
    BulkActivityPayload,
    CsvUserImportResult,
    ManagerAssignment,
    PresenceState,
    ReportingManagerChoice,
    TeamAssignment,
    TeamPresenceMember,
    TeamPresenceResponse,
    UserActivityStatsItem,
)
from app.services.csv_user_import import import_users_from_csv_bytes

log = logging.getLogger(__name__)

router = APIRouter()
admin_router = APIRouter()

PRESENCE_FRESH_MINUTES = 15


def _week_bounds_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Monday 00:00:00 UTC to next Monday 00:00:00 (exclusive)."""
    now = now or datetime.utcnow()
    days_since_monday = now.weekday()
    week_start = (now - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


def _format_duration_minutes(total: int) -> str:
    total = max(0, total)
    h, m = divmod(total, 60)
    return f"{h}h {m:02d}m"


def _format_last_active(last: ActivityLog | None) -> str:
    if last is None:
        return "No activity"
    now = datetime.utcnow()
    delta = now - last.timestamp
    if delta < timedelta(minutes=5):
        if last.status in ("ACTIVE", "SUSPICIOUS"):
            return "Active Now"
    if delta < timedelta(hours=24):
        minutes = int(delta.total_seconds() // 60)
        if minutes < 1:
            return "Just now"
        return f"{minutes} mins ago" if minutes > 1 else "1 min ago"
    if delta < timedelta(hours=48):
        return "Yesterday"
    return last.timestamp.strftime("%Y-%m-%d")


def _classify_presence(
    last: ActivityLog | None, now: datetime
) -> tuple[PresenceState, datetime | None]:
    """Return (state, last_seen_at) for team roster; state is active|idle|on_break|offline."""
    if last is None:
        return ("offline", None)
    ts = last.timestamp
    if ts.tzinfo is not None:
        ts = ts.replace(tzinfo=None)
    if now - ts > timedelta(minutes=PRESENCE_FRESH_MINUTES):
        return ("offline", ts)
    app = (last.active_app or "").strip()
    if app.lower() == "break":
        return ("on_break", ts)
    if last.status == "IDLE":
        return ("idle", ts)
    return ("active", ts)


@router.get("/team-presence", response_model=TeamPresenceResponse)
def get_team_presence(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Any:
    """
    Latest working status per user for the org, derived from the most recent
    activity log row (desktop marks breaks with active_app 'Break').
    """
    now = datetime.utcnow()

    last_sub = (
        db.query(
            ActivityLog.user_id.label("user_id"),
            func.max(ActivityLog.timestamp).label("mx"),
        ).group_by(ActivityLog.user_id)
    ).subquery()

    last_logs = {
        row.user_id: row
        for row in db.query(ActivityLog)
        .join(
            last_sub,
            and_(
                ActivityLog.user_id == last_sub.c.user_id,
                ActivityLog.timestamp == last_sub.c.mx,
            ),
        )
        .all()
    }

    users = db.query(User).order_by(User.email.asc()).all()
    members: list[TeamPresenceMember] = []
    for u in users:
        row = last_logs.get(u.id)
        state, seen = _classify_presence(row, now)
        members.append(
            TeamPresenceMember(
                user_id=u.id,
                email=u.email,
                team=u.team,
                state=state,
                last_seen_at=seen,
            )
        )

    return TeamPresenceResponse(members=members)


@router.post("/track/bulk", status_code=201)
def track_bulk_activity(
    payload: BulkActivityPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if not payload.logs:
        raise HTTPException(status_code=400, detail="No logs provided")

    db_logs = []
    for log in payload.logs:
        db_logs.append(
            ActivityLog(
                user_id=current_user.id,
                activity_score=log.activity_score,
                status=log.status,
                keyboard_entropy=log.keyboard_entropy,
                mouse_entropy=log.mouse_entropy,
                active_app=log.active_app,
                timestamp=log.timestamp,
            )
        )

    db.bulk_save_objects(db_logs)
    db.commit()

    return {"status": "success", "processed": len(db_logs)}


@router.get("/timeline", response_model=ActivityTimelineResponse)
def get_my_activity_timeline(
    day: Optional[date] = Query(
        None,
        description="UTC calendar day (YYYY-MM-DD). Defaults to today (UTC).",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """Per-minute logs for the signed-in user, aligned with the desktop agent cadence."""
    target = day or datetime.utcnow().date()
    day_start = datetime(target.year, target.month, target.day)
    day_end = day_start + timedelta(days=1)

    rows = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.user_id == current_user.id,
            ActivityLog.timestamp >= day_start,
            ActivityLog.timestamp < day_end,
        )
        .order_by(ActivityLog.timestamp.asc())
        .all()
    )

    logs: list[ActivityTimelineItem] = []
    active_m = idle_m = flagged_m = 0
    score_sum = 0.0

    for row in rows:
        ts = row.timestamp
        if ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        minute_label = ts.strftime("%H:%M")
        logs.append(
            ActivityTimelineItem(
                id=row.id,
                minute=minute_label,
                status=row.status,
                score=round(row.activity_score, 2),
            )
        )
        score_sum += row.activity_score
        if row.status == "IDLE":
            idle_m += 1
        elif row.status == "SUSPICIOUS":
            flagged_m += 1
            active_m += 1
        else:
            active_m += 1

    n = len(rows)
    avg = round(score_sum / n, 2) if n else 0.0

    return ActivityTimelineResponse(
        logs=logs,
        active_minutes=active_m,
        idle_minutes=idle_m,
        flagged_minutes=flagged_m,
        avg_score=avg,
    )


@admin_router.get("/users/stats", response_model=List[UserActivityStatsItem])
def get_user_activity_stats_for_admin(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> Any:
    """
    Per-user stats for the Team Overview: aggregate activity in the current
    ISO week (UTC), including summed activity scores, distinct days with logs,
    and active/idle minutes (one row ≈ one minute, matching the agent).
    """
    week_start, week_end = _week_bounds_utc()

    per_week = (
        db.query(
            ActivityLog.user_id.label("user_id"),
            func.count(
                distinct(cast(ActivityLog.timestamp, Date))
            ).label("days_in_week"),
            func.coalesce(func.sum(ActivityLog.activity_score), 0.0).label(
                "score_sum"
            ),
            func.coalesce(
                func.sum(case((ActivityLog.status == "IDLE", 1), else_=0)),
                0,
            ).label("idle_minutes"),
            func.coalesce(
                func.sum(case((ActivityLog.status != "IDLE", 1), else_=0)),
                0,
            ).label("active_minutes"),
        )
        .filter(
            ActivityLog.timestamp >= week_start,
            ActivityLog.timestamp < week_end,
        )
        .group_by(ActivityLog.user_id)
    ).subquery()

    last_sub = (
        db.query(
            ActivityLog.user_id.label("user_id"),
            func.max(ActivityLog.timestamp).label("mx"),
        ).group_by(ActivityLog.user_id)
    ).subquery()

    last_logs = {
        row.user_id: row
        for row in db.query(ActivityLog)
        .join(
            last_sub,
            and_(
                ActivityLog.user_id == last_sub.c.user_id,
                ActivityLog.timestamp == last_sub.c.mx,
            ),
        )
        .all()
    }

    week_rows = db.query(
        per_week.c.user_id,
        per_week.c.days_in_week,
        per_week.c.score_sum,
        per_week.c.idle_minutes,
        per_week.c.active_minutes,
    ).all()
    week_map = {r.user_id: r for r in week_rows}

    users = db.query(User).order_by(User.email).all()
    out: list[UserActivityStatsItem] = []

    for u in users:
        w = week_map.get(u.id)
        if w is None:
            days_in = 0
            score = 0.0
            idle_m = 0
            active_m = 0
        else:
            days_in = int(w.days_in_week or 0)
            score = float(w.score_sum or 0.0)
            idle_m = int(w.idle_minutes or 0)
            active_m = int(w.active_minutes or 0)

        last_row = last_logs.get(u.id)
        out.append(
            UserActivityStatsItem(
                id=u.id,
                email=u.email,
                name=u.name,
                role=u.role,
                days_worked_this_week=days_in,
                total_activity_score=round(score, 2),
                total_active_minutes=active_m,
                total_idle_minutes=idle_m,
                total_active_hours=_format_duration_minutes(active_m),
                total_idle_hours=_format_duration_minutes(idle_m),
                last_active=_format_last_active(last_row),
            )
        )

    return out


@admin_router.post("/users/import-csv", response_model=CsvUserImportResult)
async def import_users_csv(
    file: UploadFile = File(
        ...,
        description="UTF-8 CSV with header: email, password, and optional name, role, team, manager_email",
    ),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> Any:
    """
    Bulk-create users as admin. After insert, `manager_email` is resolved to `manager_id`
    if that manager exists in the database or was created in the same upload.

    See `app.services.csv_user_import` module docstring for column details and TeamCode values.
    """
    if file.filename and not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="When provided, the filename should end in .csv",
        )
    content = await file.read()
    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        return import_users_from_csv_bytes(db, content)
    except Exception as e:  # noqa: BLE001 — surface DB/validation failures to admin
        log.exception("CSV import failed")
        raise HTTPException(
            status_code=500,
            detail=f"Import failed: {e!s}",
        ) from e


@admin_router.get(
    "/reporting-managers",
    response_model=List[ReportingManagerChoice],
)
def list_reporting_manager_choices(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> Any:
    """
    Managers admins may assign — only users whose email appears in
    `MANAGER_DIRECTORY`, in that order. Unregistered directory emails are omitted.
    """
    dir_emails_lower = {m["email"].strip().lower() for m in MANAGER_DIRECTORY}
    if not dir_emails_lower:
        return []
    users = (
        db.query(User)
        .filter(func.lower(User.email).in_(dir_emails_lower))
        .all()
    )
    by_lower = {u.email.strip().lower(): u for u in users}
    out: list[ReportingManagerChoice] = []
    for m in MANAGER_DIRECTORY:
        key = m["email"].strip().lower()
        u = by_lower.get(key)
        if u is None:
            continue
        display_name = (u.name or "").strip() or m["name"]
        out.append(
            ReportingManagerChoice(
                user_id=u.id,
                email=u.email,
                name=display_name,
            )
        )
    return out


@admin_router.get("/users", response_model=List[AdminUserRow])
def list_users_for_admin(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> Any:
    """Directory of accounts for assigning reporting managers."""
    rows = db.query(User).order_by(User.email.asc()).all()
    return [
        AdminUserRow(
            id=u.id,
            email=u.email,
            name=u.name,
            role=u.role,
            manager_id=u.manager_id,
            team=u.team,
        )
        for u in rows
    ]


@admin_router.patch("/users/{user_id}/team")
def set_user_team(
    user_id: str,
    body: TeamAssignment,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> Any:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    team_val = body.team.value if body.team is not None else None
    user.team = team_val
    db.add(user)
    db.commit()
    return {"ok": True, "user_id": user.id, "team": team_val}


@admin_router.patch("/users/{user_id}/manager")
def set_user_reporting_manager(
    user_id: str,
    body: ManagerAssignment,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> Any:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    mid = body.manager_id
    if mid is not None:
        if mid == user.id:
            raise HTTPException(
                status_code=400, detail="A user cannot be their own reporting manager."
            )
        mgr = db.query(User).filter(User.id == mid).first()
        if not mgr:
            raise HTTPException(status_code=400, detail="Manager user id not found.")
        if not is_email_in_directory(mgr.email):
            raise HTTPException(
                status_code=400,
                detail="Reporting manager must be one of the configured directory managers.",
            )

    user.manager_id = mid
    db.add(user)
    db.commit()
    return {"ok": True, "user_id": user.id, "manager_id": mid}
