"""Create portable PostgreSQL backups without putting the DB password in argv."""

import os
import shutil
import subprocess
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, make_url


def _postgres_tool(name: str) -> str:
    if found := shutil.which(name):
        return found
    if os.name == "nt":
        install_root = Path(os.environ.get("ProgramFiles", r"C:\\Program Files")) / "PostgreSQL"
        if candidates := sorted(install_root.glob(f"*/bin/{name}.exe"), reverse=True):
            return str(candidates[0])
    return name


def _postgres_connection(database_url: str) -> tuple[str, dict[str, str]]:
    url = make_url(database_url)
    password = url.password
    # PostgreSQL tools do not understand SQLAlchemy's +psycopg driver suffix.
    connection_url = URL.create(
        "postgresql", username=url.username, host=url.host, port=url.port, database=url.database, query=url.query
    ).render_as_string(hide_password=False)
    environment = os.environ.copy()
    if password:
        environment["PGPASSWORD"] = password
    return connection_url, environment


def pg_dump_command(database_url: str, output_path: Path) -> tuple[list[str], dict[str, str]]:
    connection_url, environment = _postgres_connection(database_url)
    return [_postgres_tool("pg_dump"), "--format=custom", "--file", str(output_path), connection_url], environment


def pg_restore_command(database_url: str, backup_path: Path) -> tuple[list[str], dict[str, str]]:
    connection_url, environment = _postgres_connection(database_url)
    return [
        _postgres_tool("pg_restore"), "--single-transaction", "--clean", "--if-exists", "--no-owner", "--no-privileges", "--exit-on-error",
        "--dbname", connection_url, str(backup_path),
    ], environment


def create_backup(database_url: str, output_path: Path) -> None:
    command, environment = pg_dump_command(database_url, output_path)
    subprocess.run(command, env=environment, check=True, capture_output=True, timeout=300)


def restore_backup(database_url: str, backup_path: Path) -> None:
    command, environment = pg_restore_command(database_url, backup_path)
    subprocess.run(command, env=environment, check=True, capture_output=True, timeout=300)


def upgrade_schema() -> None:
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    command.upgrade(config, "head")
