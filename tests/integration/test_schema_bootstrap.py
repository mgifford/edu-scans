import sqlite3

from src.storage.schema import initialize_schema


def test_initialize_schema_creates_tables(tmp_path):
    db_path = initialize_schema(f"sqlite:///{tmp_path}/metadata.db")

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()

    assert "country_scans" in tables
    assert "domain_records" in tables
