import enum
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.team import Team


class DriveSyncStatus(str, enum.Enum):
    pending = "pending"  # saved on the server, not yet pushed to Drive (e.g. credentials not configured yet)
    uploaded = "uploaded"
    failed = "failed"


class DailyTeamPhoto(Base):
    """One group photo per team per day — a manual headcount/anti-fraud check."""

    __tablename__ = "daily_team_photos"
    __table_args__ = (
        UniqueConstraint("team_id", "year", "month", "day", name="uq_daily_photo_team_day"),
        CheckConstraint("month BETWEEN 1 AND 12", name="chk_photo_month"),
        CheckConstraint("day BETWEEN 1 AND 31", name="chk_photo_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    day: Mapped[int] = mapped_column(Integer, nullable=False)

    local_path: Mapped[str] = mapped_column(String(255), nullable=False)
    drive_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    drive_status: Mapped[DriveSyncStatus] = mapped_column(
        Enum(DriveSyncStatus, name="drive_sync_status"), default=DriveSyncStatus.pending, nullable=False
    )
    drive_error: Mapped[str | None] = mapped_column(String(255), nullable=True)

    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    team: Mapped[Team] = relationship()
