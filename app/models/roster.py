from sqlalchemy import CheckConstraint, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.employee import Employee
from app.models.team import Team


class MonthlyRoster(Base):
    __tablename__ = "monthly_roster"
    __table_args__ = (
        # employee_id+team_id+year+month (not employee_id+year+month alone) —
        # a person can be on more than one team's roster in the same month
        # (身兼数职), each team keeping its own row.
        UniqueConstraint("employee_id", "team_id", "year", "month", name="uq_roster_employee_team_month"),
        CheckConstraint("month BETWEEN 1 AND 12", name="chk_roster_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)

    employee: Mapped[Employee] = relationship()
    team: Mapped[Team] = relationship()
