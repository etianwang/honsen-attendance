"""Import the existing 人员 sheet (46 employees / 9 teams) from the old Excel
workbook into the new database, plus seed the attendance_values list and
initial accounts (1 admin + 1 team lead per team).

Usage:
    python -m seed.seed_from_excel --year 2026 --month 8
"""

import argparse
import secrets
import string
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth.security import hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import AttendanceValue, Employee, MonthlyRoster, Team, User, UserRole, ValueCategory  # noqa: E402

TEAM_ALIASES = {"仓库/电": "仓库-电"}

WORKSITE_VALUES = ["办公楼施工", "别墅施工", "美国公寓施工", "基地办公室", "基地仓库", "居家办公", "飞机", "回国", "医院"]
NOTE_WORKSITE_VALUES = ["出差", "外勤"]
NONWORK_VALUES = ["休息", "请假", "病假", "停工", "陪护", "工伤"]


def gen_password(n: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def read_roster(excel_path: Path) -> list[tuple[str, str]]:
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ws = wb["人员"]
    people = []
    for row in ws.iter_rows(min_row=3, max_col=2):
        name, team = row[0].value, row[1].value
        if not name:
            continue
        team = TEAM_ALIASES.get(team, team) if team else "未分组"
        people.append((str(name).strip(), str(team).strip()))
    return people


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--excel", default=str(Path(__file__).resolve().parent.parent / "科特迪瓦考勤登记表2026.xlsx"))
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--admin-username", default="admin")
    parser.add_argument("--admin-password", default=None)
    args = parser.parse_args()

    people = read_roster(Path(args.excel))
    db = SessionLocal()
    try:
        team_names = sorted({t for _, t in people})
        teams_by_name = {}
        for name in team_names:
            team = db.query(Team).filter(Team.name == name).one_or_none()
            if team is None:
                team = Team(name=name)
                db.add(team)
                db.flush()
            teams_by_name[name] = team

        added_employees = 0
        added_roster = 0
        for name, team_name in people:
            employee = db.query(Employee).filter(Employee.full_name == name).one_or_none()
            if employee is None:
                employee = Employee(full_name=name)
                db.add(employee)
                db.flush()
                added_employees += 1
            existing_roster = (
                db.query(MonthlyRoster)
                .filter(
                    MonthlyRoster.employee_id == employee.id,
                    MonthlyRoster.year == args.year,
                    MonthlyRoster.month == args.month,
                )
                .one_or_none()
            )
            if existing_roster is None:
                db.add(
                    MonthlyRoster(
                        employee_id=employee.id,
                        team_id=teams_by_name[team_name].id,
                        year=args.year,
                        month=args.month,
                    )
                )
                added_roster += 1

        added_values = 0

        def ensure_value(code: str, category: ValueCategory, requires_note: bool = False, sort_order: int = 0):
            nonlocal added_values
            existing = db.query(AttendanceValue).filter(AttendanceValue.code == code).one_or_none()
            if existing is None:
                db.add(
                    AttendanceValue(
                        code=code, category=category, requires_note=requires_note, sort_order=sort_order
                    )
                )
                added_values += 1

        for i, code in enumerate(WORKSITE_VALUES):
            ensure_value(code, ValueCategory.worksite, sort_order=i)
        for i, code in enumerate(NOTE_WORKSITE_VALUES):
            ensure_value(code, ValueCategory.worksite, requires_note=True, sort_order=100 + i)
        for i, code in enumerate(NONWORK_VALUES):
            ensure_value(code, ValueCategory.nonwork, sort_order=i)

        created_accounts = []
        admin = db.query(User).filter(User.username == args.admin_username).one_or_none()
        if admin is None:
            pw = args.admin_password or gen_password()
            db.add(
                User(
                    username=args.admin_username,
                    password_hash=hash_password(pw),
                    display_name="管理员",
                    role=UserRole.admin,
                )
            )
            created_accounts.append((args.admin_username, pw, "admin"))

        for name in team_names:
            team = teams_by_name[name]
            username = f"lead_{name}"
            existing = db.query(User).filter(User.username == username).one_or_none()
            if existing is None:
                pw = gen_password()
                db.add(
                    User(
                        username=username,
                        password_hash=hash_password(pw),
                        display_name=f"{name}班组长",
                        role=UserRole.team_lead,
                        team_id=team.id,
                    )
                )
                created_accounts.append((username, pw, f"team_lead:{name}"))

        db.commit()

        print(f"班组: {len(team_names)} 个 ({', '.join(team_names)})")
        print(f"新增员工: {added_employees} 人")
        print(f"{args.year}年{args.month}月 花名册新增: {added_roster} 人")
        print(f"新增可选值: {added_values} 个")
        if created_accounts:
            print("\n新建账号（请分发后自行修改密码）:")
            for username, pw, role in created_accounts:
                print(f"  {username}  /  {pw}   ({role})")
        else:
            print("\n没有新建账号（可能已存在）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
