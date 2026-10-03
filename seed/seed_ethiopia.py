"""Fresh seed for the Ethiopia deployment: one team, one worksite, no legacy
data imported. Employees get added afterward through the roster page.

Usage:
    python -m seed.seed_ethiopia
"""

import argparse
import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth.security import hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import AttendanceValue, Team, User, UserRole, ValueCategory  # noqa: E402

TEAM_NAME = "埃塞酒店团队"

WORKSITE_VALUES = ["万豪酒店", "基地办公室", "居家办公", "飞机", "回国", "医院"]
NOTE_WORKSITE_VALUES = ["出差", "外勤"]
NONWORK_VALUES = ["休息", "请假", "病假", "停工", "陪护", "工伤"]


def gen_password(n: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-username", default="admin")
    parser.add_argument("--admin-password", default=None)
    parser.add_argument("--lead-username", default="lifan")
    parser.add_argument("--lead-password", default=None)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        team = db.query(Team).filter(Team.name == TEAM_NAME).one_or_none()
        if team is None:
            team = Team(name=TEAM_NAME)
            db.add(team)
            db.flush()
            print(f"新建班组: {TEAM_NAME}")
        else:
            print(f"班组已存在: {TEAM_NAME}")

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

        lead = db.query(User).filter(User.username == args.lead_username).one_or_none()
        if lead is None:
            pw = args.lead_password or gen_password()
            db.add(
                User(
                    username=args.lead_username,
                    password_hash=hash_password(pw),
                    display_name=f"{TEAM_NAME}班组长",
                    role=UserRole.team_lead,
                    team_id=team.id,
                )
            )
            created_accounts.append((args.lead_username, pw, f"team_lead:{TEAM_NAME}"))

        db.commit()

        print(f"新增可选值: {added_values} 个")
        print("没有导入员工/花名册 —— 请登录后在花名册页面手动添加组员。")
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
