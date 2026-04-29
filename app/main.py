from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api import routes_auth, routes_activity, routes_mail, websockets
from app.core.config import settings
from app.models.base import Base, engine

# Ensure DB tables are created (in production, use Alembic via CLI instead of this)
Base.metadata.create_all(bind=engine)


def ensure_manager_id_column() -> None:
    """Add manager_id to existing SQLite/Postgres DBs created before this column existed."""
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        return
    cols = [c["name"] for c in inspector.get_columns("users")]
    if "manager_id" in cols:
        return
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "postgresql":
            conn.execute(
                text("ALTER TABLE users ADD COLUMN manager_id VARCHAR REFERENCES users(id)")
            )
        else:
            conn.execute(text("ALTER TABLE users ADD COLUMN manager_id VARCHAR"))


ensure_manager_id_column()


def ensure_team_column() -> None:
    """Add team to existing SQLite/Postgres DBs created before this column existed."""
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        return
    cols = [c["name"] for c in inspector.get_columns("users")]
    if "team" in cols:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN team VARCHAR"))


ensure_team_column()


def ensure_name_column() -> None:
    """Add name to existing DBs created before this column existed."""
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        return
    cols = [c["name"] for c in inspector.get_columns("users")]
    if "name" in cols:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN name VARCHAR"))


ensure_name_column()

app = FastAPI(
    title="Enterprise Time Tracker API",
    description="Backend for the desktop agent and web dashboard",
    version="1.0.0"
)

# CORS origins are read from the CORS_ORIGINS environment variable.
# Set it in .env or in AWS Secrets Manager / ECS task env:
#   CORS_ORIGINS=https://app.yourdomain.com,http://localhost:3000
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(routes_auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(routes_activity.admin_router, prefix="/api/admin", tags=["Admin"])
app.include_router(routes_activity.router, prefix="/api/activity", tags=["Activity Tracking"])
app.include_router(routes_mail.router, prefix="/api/mail", tags=["Mail"])
app.include_router(websockets.router, prefix="/api/ws", tags=["Real-time WebSockets"])

@app.get("/health")
def health_check():
    return {"status": "online", "message": "API is operational."}