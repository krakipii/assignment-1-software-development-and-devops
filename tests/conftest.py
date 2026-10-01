"""Shared test setup, every test gets its own empty SQLite database."""
import pytest

import database


@pytest.fixture
def conn(tmp_path):
    """An open connection to a new database with all tables created.

    tmp_path is a temporary folder that pytest creates for each test, this way
    test ever sees data from another test or touches the real data or folder.
    """
    connection = database.get_connection(str(tmp_path / "test.db"))
    database.init_db(connection)
    yield connection
    connection.close()