from sqlalchemy import Column, String, Float, DateTime, ForeignKey
from app.models.base import Base
from datetime import datetime
import uuid

class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(String, ForeignKey("users.id"), index=True, nullable=False)
    activity_score = Column(Float, nullable=False)
    status = Column(String, index=True, nullable=False)
    keyboard_entropy = Column(Float, nullable=False)
    mouse_entropy = Column(Float, nullable=False)
    active_app = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)