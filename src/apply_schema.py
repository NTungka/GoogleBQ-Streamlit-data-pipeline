"""
Apply staging_schema.sql to the Cloud SQL Postgres instance using the same
Cloud SQL Python Connector setup as load_to_cloudsql.py -- avoids needing a
local psql client install.

Usage:
    python apply_schema.py
"""

import os
from pathlib import Path

import sqlalchemy
from dotenv import load_dotenv
from google.cloud.sql.connector import Connector

load_dotenv()

DATA_DIR = Path(__file__).parent
SCHEMA_FILE = DATA_DIR / "staging_schema.sql"

INSTANCE_CONNECTION_NAME = os.environ["INSTANCE_CONNECTION_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASS = os.environ["DB_PASS"]
DB_NAME = os.environ["DB_NAME"]


def strip_comments(sql_text: str) -> str:
    # Removes "--" line comments. Safe for this file specifically: no block
    # comments, and no "--" or ";" appears inside a string literal anywhere
    # in staging_schema.sql.
    return "\n".join(line.split("--", 1)[0] for line in sql_text.splitlines())


def main() -> None:
    sql_text = strip_comments(SCHEMA_FILE.read_text())
    statements = [s.strip() for s in sql_text.split(";") if s.strip()]

    connector = Connector()
    try:
        def getconn():
            return connector.connect(
                INSTANCE_CONNECTION_NAME,
                "pg8000",
                user=DB_USER,
                password=DB_PASS,
                db=DB_NAME,
            )

        engine = sqlalchemy.create_engine("postgresql+pg8000://", creator=getconn)

        with engine.begin() as conn:
            for stmt in statements:
                print(f"Executing: {stmt[:80]}...")
                conn.execute(sqlalchemy.text(stmt))

        print(f"\nApplied {len(statements)} statements from {SCHEMA_FILE.name}.")
    finally:
        connector.close()


if __name__ == "__main__":
    main()
