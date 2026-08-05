import enum

from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ValueCategory(str, enum.Enum):
    worksite = "worksite"  # counts as worked (includes 出差/外勤 with a note, and 医院/飞机 etc.)
    nonwork = "nonwork"    # counts toward the pooled monthly rest quota


class AttendanceValue(Base):
    __tablename__ = "attendance_values"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    category: Mapped[ValueCategory] = mapped_column(Enum(ValueCategory, name="value_category"), nullable=False)
    requires_note: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
