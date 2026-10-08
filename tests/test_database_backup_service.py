from pathlib import Path

from app.services.database_backup_service import pg_dump_command, pg_restore_command


def test_backup_command_uses_postgres_url_without_password_in_arguments():
    command, environment = pg_dump_command(
        "postgresql+psycopg://attendance:secret@db.example:5432/attendance", Path("backup.dump")
    )

    assert Path(command[0]).name in ("pg_dump", "pg_dump.exe")
    assert command[-1] == "postgresql://attendance@db.example:5432/attendance"
    assert "secret" not in " ".join(command)
    assert environment["PGPASSWORD"] == "secret"


def test_restore_command_overwrites_data_without_exposing_password():
    command, environment = pg_restore_command(
        "postgresql+psycopg://attendance:secret@db.example:5432/attendance", Path("backup.dump")
    )

    assert Path(command[0]).name in ("pg_restore", "pg_restore.exe")
    assert "--single-transaction" in command
    assert "--clean" in command
    assert command[-2] == "postgresql://attendance@db.example:5432/attendance"
    assert "secret" not in " ".join(command)
    assert environment["PGPASSWORD"] == "secret"
