"""Database initialization for this project.

If the database hasn't been migrated yet, runs all Alembic migrations
(equivalent to `alembic upgrade head`) and prints the table structure that
was just created. If it's already been initialized, does nothing and prints
the existing table structure instead.

Usage:
    python init_db.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.runtime.migration import MigrationContext  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

from app.database import engine  # noqa: E402


def get_current_revision() -> str | None:
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        return context.get_current_revision()


def print_schema() -> None:
    inspector = inspect(engine)
    table_names = sorted(inspector.get_table_names())
    if not table_names:
        print("（数据库里没有任何表）")
        return

    for table_name in table_names:
        print(f"\n表: {table_name}")
        pk_constraint = inspector.get_pk_constraint(table_name)
        pk_cols = set(pk_constraint.get("constrained_columns") or [])

        fk_map = {}
        for fk in inspector.get_foreign_keys(table_name):
            # zip, not a nested loop over referred_columns[0] — composite FKs
            # (e.g. attendance_entries -> monthly_roster on employee_id+year+month)
            # otherwise all get mapped to the first referred column.
            for local_col, ref_col in zip(fk["constrained_columns"], fk["referred_columns"]):
                fk_map[local_col] = f"{fk['referred_table']}.{ref_col}"

        for col in inspector.get_columns(table_name):
            flags = []
            if col["name"] in pk_cols:
                flags.append("PK")
            if col["name"] in fk_map:
                flags.append(f"FK->{fk_map[col['name']]}")
            if not col["nullable"]:
                flags.append("NOT NULL")
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            print(f"  {col['name']:<28} {str(col['type']):<24}{flag_str}")

        for uq in inspector.get_unique_constraints(table_name):
            if uq.get("column_names"):
                print(f"  UNIQUE({', '.join(uq['column_names'])})")


def main() -> None:
    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))

    current_revision = get_current_revision()

    if current_revision is not None:
        print(f"数据库已经初始化过（当前迁移版本: {current_revision}），不需要重复建表。")
        print("现有表结构：")
        print_schema()
        sys.exit(0)

    print("数据库里还没有表，开始建表...")
    command.upgrade(alembic_cfg, "head")
    print("\n建表完成，新建的表结构：")
    print_schema()


if __name__ == "__main__":
    main()
