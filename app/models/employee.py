import enum

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EmployeeStatus(str, enum.Enum):
    active = "active"
    returned = "returned"
    suspended = "suspended"


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Unique — same-name-different-person isn't handled; a name collision is
    # treated as an error the admin resolves (edit one of them), not a case
    # the system tries to disambiguate on its own.
    full_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    blood_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    avatar_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[EmployeeStatus] = mapped_column(
        Enum(EmployeeStatus, name="employee_status"),
        nullable=False,
        default=EmployeeStatus.active,
        server_default=EmployeeStatus.active.value,
    )
