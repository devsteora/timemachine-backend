from enum import Enum

from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import List, Literal, Optional


class TeamCode(str, Enum):
    DEV = "DEV"
    QC = "QC"
    AV = "AV"
    TRANSCRIPTION = "TRANSCRIPTION"
    ACCOUNTS = "ACCOUNTS"
    ORDER_DESK = "ORDER_DESK"
    HR = "HR"
    ADMIN = "ADMIN"

# --- User Schemas ---
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: str = "EMPLOYEE"
    name: Optional[str] = Field(None, max_length=200)

class UserResponse(BaseModel):
    id: str
    email: EmailStr
    role: str
    name: Optional[str] = None

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

# --- Activity Schemas ---
class ActivityPayload(BaseModel):
    activity_score: float
    status: str
    keyboard_entropy: float
    mouse_entropy: float
    active_app: Optional[str] = None
    timestamp: datetime

class BulkActivityPayload(BaseModel):
    logs: List[ActivityPayload]


class ActivityTimelineItem(BaseModel):
    id: str
    minute: str
    status: str
    score: float


class ActivityTimelineResponse(BaseModel):
    logs: List[ActivityTimelineItem]
    active_minutes: int
    idle_minutes: int
    flagged_minutes: int
    avg_score: float


# --- Admin ---
class UserActivityStatsItem(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    role: str
    days_worked_this_week: int
    total_activity_score: float
    total_active_minutes: int
    total_idle_minutes: int
    total_active_hours: str
    total_idle_hours: str
    last_active: str


# --- Mail / reporting manager ---
class ReportingManagerResponse(BaseModel):
    email: Optional[str] = None
    manager_user_id: Optional[str] = None


class ManagerDirectoryEntry(BaseModel):
    name: str
    email: EmailStr


class MailComposeContextResponse(BaseModel):
    managers: List[ManagerDirectoryEntry]
    assigned_manager_email: Optional[str] = None


class MailSendRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1, max_length=50_000)
    recipient_email: EmailStr


class MailSendResponse(BaseModel):
    ok: bool = True
    sent_to: str


class AdminUserRow(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    role: str
    manager_id: Optional[str] = None
    team: Optional[str] = None


class CsvUserImportRowError(BaseModel):
    row_number: int
    email: Optional[str] = None
    detail: str


class CsvUserImportResult(BaseModel):
    created: int
    failed: int
    errors: List[CsvUserImportRowError] = []
    manager_warnings: List[CsvUserImportRowError] = []


class ManagerAssignment(BaseModel):
    manager_id: Optional[str] = None


class TeamAssignment(BaseModel):
    team: Optional[TeamCode] = None


PresenceState = Literal["active", "idle", "on_break", "offline"]


class TeamPresenceMember(BaseModel):
    user_id: str
    email: str
    team: Optional[str] = None
    state: PresenceState
    last_seen_at: Optional[datetime] = None


class TeamPresenceResponse(BaseModel):
    members: List[TeamPresenceMember]
