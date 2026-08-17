import pytest
from pydantic import SecretStr

from transport_platform.database.initialise import _validate_database_name
from transport_platform.database.sql_server import build_connection_string
from transport_platform.settings import Settings


def test_build_connection_string_uses_local_configuration() -> None:
    settings = Settings(
        tfgm_gtfs_url="https://example.test/gtfs.zip",
        sql_server_host="127.0.0.1",
        sql_server_port=14330,
        sql_server_database="transport_test",
        sql_server_username="sa",
        sql_server_password=SecretStr("LocalPassword_123!"),
    )

    connection_string = build_connection_string(settings)

    assert "SERVER={127.0.0.1,14330}" in connection_string
    assert "DATABASE={transport_test}" in connection_string
    assert "UID={sa}" in connection_string
    assert "PWD={LocalPassword_123!}" in connection_string
    assert "AZURE" not in connection_string.upper()


def test_database_name_validation_accepts_safe_name() -> None:
    _validate_database_name("greater_manchester_transport")


def test_database_name_validation_rejects_sql_content() -> None:
    with pytest.raises(ValueError, match="letters, numbers and underscores"):
        _validate_database_name("transport]; DROP DATABASE master;")


def test_connection_string_requires_database_password() -> None:
    settings = Settings(
        tfgm_gtfs_url="https://example.test/gtfs.zip",
        sql_server_password=SecretStr(""),
    )

    with pytest.raises(ValueError, match="SQL_SERVER_PASSWORD is required"):
        build_connection_string(settings)
