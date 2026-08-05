from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.attendance_value import AttendanceValue
from app.models.employee import Employee
from app.models.team import Team


class AttendanceEntry(Base):
    """One row per (employee, team, day) — not just per (employee, day).

    An employee who works for two teams in the same month (身兼数职) gets one
    independent row per team per day, so each team lead's entry never
    overwrites the other team's. Personal monthly quota stats collapse
    across these rows (see stats.bulk_month_breakdown); site×team labor
    stats intentionally do NOT collapse — each team's own row is its own
    credit (see stats.labor_stats / person_site_team_stats)."""

    __tablename__ = "attendance_entries"
    __table_args__ = (
        UniqueConstraint("employee_id", "team_id", "year", "month", "day", name="uq_entry_employee_team_day"),
        CheckConstraint("month BETWEEN 1 AND 12", name="chk_entry_month"),
        CheckConstraint("day BETWEEN 1 AND 31", name="chk_entry_day"),
        ForeignKeyConstraint(
            ["employee_id", "team_id", "year", "month"],
            ["monthly_roster.employee_id", "monthly_roster.team_id", "monthly_roster.year", "monthly_roster.month"],
            name="fk_entry_roster",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    day: Mapped[int] = mapped_column(Integer, nullable=False)

    # Nullable: a half-day left unset is exactly the "incomplete" state the
    # daily entry page needs to flag until the team lead fills it in.
    am_value_id: Mapped[int | None] = mapped_column(ForeignKey("attendance_values.id"), nullable=True)
    am_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pm_value_id: Mapped[int | None] = mapped_column(ForeignKey("attendance_values.id"), nullable=True)
    pm_note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    evening_overtime: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    edited_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    edited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    employee: Mapped[Employee] = relationship(foreign_keys=[employee_id])
    team: Mapped[Team] = relationship(foreign_keys=[team_id])
    am_value: Mapped[Optional[AttendanceValue]] = relationship(foreign_keys=[am_value_id])
    pm_value: Mapped[Optional[AttendanceValue]] = relationship(foreign_keys=[pm_value_id])
