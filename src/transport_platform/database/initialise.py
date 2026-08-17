from __future__ import annotations

import re
from pathlib import Path

from transport_platform.database.sql_server import connect
from transport_platform.settings import Settings, get_settings

DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
DDL_DIRECTORY = Path(__file__).resolve().parents[3] / "sql" / "ddl"


def _validate_database_name(database_name: str) -> None:
    """Reject database names that cannot be safely quoted in DDL."""

    if not DATABASE_NAME_PATTERN.fullmatch(database_name):
        raise ValueError(
            "SQL_SERVER_DATABASE must start with a letter and contain "
            "only letters, numbers and underscores"
        )


def ensure_database(settings: Settings) -> None:
    """Create the configured development database when it does not exist."""

    database_name = settings.sql_server_database
    _validate_database_name(database_name)

    with connect(database="master", autocommit=True, settings=settings) as connection:
        cursor = connection.cursor()
        database_exists = cursor.execute(
            "SELECT 1 FROM sys.databases WHERE name = ?;",
            database_name,
        ).fetchone()

        if database_exists is None:
            cursor.execute(f"CREATE DATABASE [{database_name}];")
            print(f"Created database: {database_name}")
        else:
            print(f"Database already exists: {database_name}")


def apply_ddl(settings: Settings) -> None:
    """Apply all ordered, idempotent warehouse DDL files."""

    ddl_paths = sorted(DDL_DIRECTORY.glob("*.sql"))
    if not ddl_paths:
        raise FileNotFoundError(f"No DDL files found in {DDL_DIRECTORY}")

    with connect(settings=settings) as connection:
        cursor = connection.cursor()

        for ddl_path in ddl_paths:
            script = ddl_path.read_text(encoding="utf-8")
            print(f"Applying: {ddl_path.name}")

            try:
                cursor.execute(script)
                while cursor.nextset():
                    pass
                connection.commit()
            except Exception:
                connection.rollback()
                raise


def initialise_database() -> None:
    """Create the local database and apply the warehouse schema."""

    settings = get_settings()
    ensure_database(settings)
    apply_ddl(settings)
    print("Local SQL Server database initialisation completed")


if __name__ == "__main__":
    initialise_database()
