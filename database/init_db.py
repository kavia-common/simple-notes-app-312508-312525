#!/usr/bin/env python3
"""Initialize and migrate the SQLite database for this project.

This script is intentionally deterministic and safe to run multiple times:
- Creates core tables if they don't exist.
- Applies non-destructive migrations (adds missing columns) when tables exist.
- Writes/updates db_connection.txt and db_visualizer/sqlite.env so other helper tools keep working.

Rerun this script any time (e.g., after deleting a table) to recover the schema:
    python3 init_db.py
"""

import os
import re
import sqlite3
from typing import Dict, List, Optional, Tuple

DB_NAME = "myapp.db"
DB_USER = "kaviasqlite"  # Not used for SQLite, but kept for consistency
DB_PASSWORD = "kaviadefaultpassword"  # Not used for SQLite, but kept for consistency
DB_PORT = "5000"  # Not used for SQLite, but kept for consistency


def _parse_db_path_from_connection_file(path: str) -> Optional[str]:
    """Parse an absolute SQLite file path from db_connection.txt, if present."""
    if not os.path.exists(path):
        return None
    try:
        content = open(path, "r", encoding="utf-8").read()
    except Exception:
        return None

    # Prefer "# File path: /abs/path/to/myapp.db"
    m = re.search(r"^#\s*File path:\s*(.+)$", content, flags=re.MULTILINE)
    if m:
        candidate = m.group(1).strip()
        if candidate:
            return candidate

    # Fallback: "# Connection string: sqlite:////abs/path/to/myapp.db"
    m = re.search(r"^#\s*Connection string:\s*sqlite:////(.+)$", content, flags=re.MULTILINE)
    if m:
        candidate = "/" + m.group(1).strip()
        if candidate:
            return candidate

    return None


def _resolve_db_path() -> str:
    """Resolve SQLite DB path using db_connection.txt if available; otherwise default to local DB_NAME."""
    # If db_connection.txt is present, treat it as authoritative for locating the DB file.
    from_connection = _parse_db_path_from_connection_file("db_connection.txt")
    if from_connection:
        # If path is relative, resolve relative to current working dir.
        return os.path.abspath(from_connection)

    return os.path.abspath(DB_NAME)


def _table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    """Return True if table exists in the SQLite database."""
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def _get_table_columns(cursor: sqlite3.Cursor, table_name: str) -> Dict[str, Tuple[str, int, Optional[str]]]:
    """Return mapping of column_name -> (declared_type, notnull, default_value)."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    rows = cursor.fetchall()
    # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
    return {r[1]: (r[2], r[3], r[4]) for r in rows}


def _ensure_table_with_required_columns(
    cursor: sqlite3.Cursor,
    table_name: str,
    create_sql: str,
    required_columns: List[Tuple[str, str]],
) -> None:
    """Ensure a table exists and add missing required columns non-destructively.

    Args:
        table_name: Table to ensure.
        create_sql: CREATE TABLE IF NOT EXISTS ... statement.
        required_columns: List of (column_name, column_definition_suffix) suitable for ALTER TABLE ADD COLUMN.
                         Example: ("updated_at", "TEXT DEFAULT CURRENT_TIMESTAMP")
    """
    cursor.execute(create_sql)

    existing_cols = _get_table_columns(cursor, table_name)
    for col_name, col_def in required_columns:
        if col_name in existing_cols:
            continue
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}")


def _ensure_notes_updated_at_trigger(cursor: sqlite3.Cursor) -> None:
    """Ensure a trigger exists to auto-update notes.updated_at on UPDATE.

    SQLite does not support an 'ON UPDATE CURRENT_TIMESTAMP' column clause, so we use a trigger.
    The trigger is created idempotently using IF NOT EXISTS.
    """
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS notes_set_updated_at
        AFTER UPDATE ON notes
        FOR EACH ROW
        WHEN NEW.updated_at = OLD.updated_at
        BEGIN
            UPDATE notes
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = NEW.id;
        END;
        """
    )


def main() -> None:
    """Main entrypoint: connect, ensure schema, write helper files."""
    print("Starting SQLite setup...")

    db_path = _resolve_db_path()
    db_dir = os.path.dirname(db_path) or "."
    os.makedirs(db_dir, exist_ok=True)

    db_exists = os.path.exists(db_path)
    if db_exists:
        print(f"SQLite database already exists at {db_path}")
    else:
        print(f"Creating new SQLite database at {db_path}...")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")

        # Core schema (kept for compatibility with existing template)
        _ensure_table_with_required_columns(
            cursor,
            table_name="app_info",
            create_sql="""
                CREATE TABLE IF NOT EXISTS app_info (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            required_columns=[],
        )

        _ensure_table_with_required_columns(
            cursor,
            table_name="users",
            create_sql="""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            required_columns=[],
        )

        # Notes schema required by the app
        _ensure_table_with_required_columns(
            cursor,
            table_name="notes",
            create_sql="""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """,
            required_columns=[
                ("title", "TEXT NOT NULL DEFAULT ''"),
                ("content", "TEXT NOT NULL DEFAULT ''"),
                ("created_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
                ("updated_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
            ],
        )

        # Trigger for updated_at auto-update
        _ensure_notes_updated_at_trigger(cursor)

        # Insert initial data (deterministic: idempotent via INSERT OR REPLACE on UNIQUE key)
        cursor.execute(
            "INSERT OR REPLACE INTO app_info (key, value) VALUES (?, ?)",
            ("project_name", "database"),
        )
        cursor.execute(
            "INSERT OR REPLACE INTO app_info (key, value) VALUES (?, ?)",
            ("version", "0.1.0"),
        )
        cursor.execute(
            "INSERT OR REPLACE INTO app_info (key, value) VALUES (?, ?)",
            ("author", "John Doe"),
        )
        cursor.execute(
            "INSERT OR REPLACE INTO app_info (key, value) VALUES (?, ?)",
            ("description", ""),
        )

        conn.commit()

        # Get database statistics
        cursor.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        table_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM app_info")
        record_count = cursor.fetchone()[0]

    except Exception as e:
        print(f"Database setup failed: {e}")
        raise
    finally:
        if "conn" in locals():
            conn.close()

    # Save connection information to a file (keep helper tools working)
    connection_string = f"sqlite:///{db_path}"

    try:
        with open("db_connection.txt", "w", encoding="utf-8") as f:
            f.write("# SQLite connection methods:\n")
            f.write(f"# Python: sqlite3.connect('{os.path.basename(db_path)}')\n")
            f.write(f"# Connection string: {connection_string}\n")
            f.write(f"# File path: {db_path}\n")
        print("Connection information saved to db_connection.txt")
    except Exception as e:
        print(f"Warning: Could not save connection info: {e}")

    # Create environment variables file for Node.js viewer
    if not os.path.exists("db_visualizer"):
        os.makedirs("db_visualizer", exist_ok=True)
        print("Created db_visualizer directory")

    try:
        with open("db_visualizer/sqlite.env", "w", encoding="utf-8") as f:
            f.write(f'export SQLITE_DB="{db_path}"\n')
        print("Environment variables saved to db_visualizer/sqlite.env")
    except Exception as e:
        print(f"Warning: Could not save environment variables: {e}")

    print("\nSQLite setup complete!")
    print(f"Database: {os.path.basename(db_path)}")
    print(f"Location: {db_path}\n")

    print("Schema initialization / migration notes:")
    print("  - This script can be rerun safely; it creates missing tables and adds missing columns.")
    print("  - The notes.updated_at field is maintained via a trigger on UPDATE.\n")

    print("To use with Node.js viewer, run: source db_visualizer/sqlite.env\n")
    print("To connect to the database, use one of the following methods:")
    print(f"1. Python: sqlite3.connect('{os.path.basename(db_path)}')")
    print(f"2. Connection string: {connection_string}")
    print(f"3. Direct file access: {db_path}\n")

    print("Database statistics:")
    print(f"  Tables: {table_count}")
    print(f"  App info records: {record_count}")

    # If sqlite3 CLI is available, show how to use it
    try:
        import subprocess

        result = subprocess.run(["which", "sqlite3"], capture_output=True, text=True)
        if result.returncode == 0:
            print("\nSQLite CLI is available. You can also use:")
            print(f"  sqlite3 {os.path.basename(db_path)}")
    except Exception:
        pass

    print("\nScript completed successfully.")


if __name__ == "__main__":
    main()
