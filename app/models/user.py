from sqlalchemy import Column, String, Enum, ForeignKey
from app.models.base import Base
import uuid

class RoleEnum(str, Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    EMPLOYEE = "EMPLOYEE"

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    name = Column(String, nullable=True)
    role = Column(String, default="EMPLOYEE", nullable=False)
    manager_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    team = Column(String, nullable=True, index=True)