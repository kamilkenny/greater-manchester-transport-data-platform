from __future__ import annotations

from typing import TYPE_CHECKING

from transport_platform.settings import Settings, get_settings

if TYPE_CHECKING:
    import pyodbc


def _odbc_value(value: object) -> str:
    """Escape one value for use in an ODBC connection string."""

    return "{" + str(value).replace("}", "}}") + "}"


def build_connection_string(
    settings: Settings,
    database: str | None = None,
) -> str:
    """Build a SQL Server ODBC connection string without logging secrets."""

    password = settings.sql_server_password.get_secret_value()
    if not password:
        raise ValueError(
            "SQL_SERVER_PASSWORD is required for a database connection"
        )

    target_database = database or settings.sql_server_database
    server = f"{settings.sql_server_host},{settings.sql_server_port}"

    values = {
        "DRIVER": settings.sql_server_driver,
        "SERVER": server,
        "DATABASE": target_database,
        "UID": settings.sql_server_username,
        "PWD": password,
        "Encrypt": "yes" if settings.sql_server_encrypt else "no",
        "TrustServerCertificate": (
            "yes" if settings.sql_server_trust_certificate else "no"
        ),
    }

    return ";".join(
        f"{key}={_odbc_value(value)}" for key, value in values.items()
    )


def build_bulk_connection_string(
    settings: Settings,
    database: str | None = None,
) -> str:
    """Build a connection string for Microsoft's native Python driver."""

    password = settings.sql_server_password.get_secret_value()
    if not password:
        raise ValueError(
            "SQL_SERVER_PASSWORD is required for a database connection"
        )

    target_database = database or settings.sql_server_database
    server = f"{settings.sql_server_host},{settings.sql_server_port}"
    values = {
        "SERVER": server,
        "DATABASE": target_database,
        "UID": settings.sql_server_username,
        "PWD": password,
        "Encrypt": "yes" if settings.sql_server_encrypt else "no",
        "TrustServerCertificate": (
            "yes" if settings.sql_server_trust_certificate else "no"
        ),
    }
    return ";".join(
        f"{key}={_odbc_value(value)}" for key, value in values.items()
    )


def connect(
    *,
    database: str | None = None,
    autocommit: bool = False,
    settings: Settings | None = None,
) -> pyodbc.Connection:
    """Open a connection to the configured local SQL Server instance."""

    import pyodbc

    resolved_settings = settings or get_settings()
    connection_string = build_connection_string(
        resolved_settings,
        database=database,
    )
    return pyodbc.connect(connection_string, autocommit=autocommit)


def connect_bulk(
    *,
    database: str | None = None,
    settings: Settings | None = None,
):
    """Open a native SQL Server connection for bulk copy operations."""

    import mssql_python

    resolved_settings = settings or get_settings()
    connection_string = build_bulk_connection_string(
        resolved_settings,
        database=database,
    )
    return mssql_python.connect(connection_string, timeout=60)
