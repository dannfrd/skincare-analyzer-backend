import argparse
import os
import re
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError


def split_sql_statements(sql_script: str) -> List[str]:
    """Split SQL script into individual statements while respecting quoted strings."""
    statements: List[str] = []

    # Drop full-line comments prefixed with '--'.
    filtered_lines = []
    for line in sql_script.splitlines():
        if line.strip().startswith("--"):
            continue
        filtered_lines.append(line)

    cleaned_script = "\n".join(filtered_lines)

    current = []
    in_single_quote = False
    in_double_quote = False
    in_backtick = False
    escaped = False

    for ch in cleaned_script:
        current.append(ch)

        if escaped:
            escaped = False
            continue

        if ch == "\\":
            escaped = True
            continue

        if ch == "'" and not in_double_quote and not in_backtick:
            in_single_quote = not in_single_quote
        elif ch == '"' and not in_single_quote and not in_backtick:
            in_double_quote = not in_double_quote
        elif ch == "`" and not in_single_quote and not in_double_quote:
            in_backtick = not in_backtick
        elif ch == ";" and not in_single_quote and not in_double_quote and not in_backtick:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)

    return statements


def build_urls() -> tuple[URL, URL, str]:
    load_dotenv()

    db_host = os.getenv("DB_HOST", "localhost")
    db_user = os.getenv("DB_USER", "root")
    db_password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME", "skincare_analyzer")
    db_port_raw = os.getenv("DB_PORT", "")

    if not re.match(r"^[A-Za-z0-9_]+$", db_name):
        raise ValueError("DB_NAME hanya boleh berisi huruf, angka, dan underscore.")

    db_port = int(db_port_raw) if db_port_raw else None

    base_url = URL.create(
        drivername="mysql+pymysql",
        username=db_user,
        password=db_password or None,
        host=db_host,
        port=db_port,
    )
    database_url = base_url.set(database=db_name)
    return base_url, database_url, db_name


def ensure_database_exists(base_url: URL, db_name: str) -> None:
    engine = create_engine(base_url)
    create_db_sql = f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"

    with engine.begin() as conn:
        conn.execute(text(create_db_sql))


def apply_migration(database_url: URL, migration_file: Path) -> None:
    sql_script = migration_file.read_text(encoding="utf-8")
    statements = split_sql_statements(sql_script)

    if not statements:
        raise RuntimeError("Tidak ada statement SQL yang ditemukan di file migration.")

    engine = create_engine(database_url)

    with engine.begin() as conn:
        for i, stmt in enumerate(statements, start=1):
            try:
                conn.execute(text(stmt))
                print(f"[{i}/{len(statements)}] OK")
            except SQLAlchemyError as exc:
                error_text = str(exc)
                # Allow repeated runs when index already exists.
                if "Duplicate key name" in error_text:
                    print(f"[{i}/{len(statements)}] SKIP (index sudah ada)")
                    continue
                raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SQL migration file to MySQL database.")
    parser.add_argument(
        "--file",
        default=str(Path(__file__).with_name("migration.sql")),
        help="Path ke file migration SQL (default: database/migration.sql)",
    )
    args = parser.parse_args()

    migration_file = Path(args.file).resolve()
    if not migration_file.exists():
        raise FileNotFoundError(f"File migration tidak ditemukan: {migration_file}")

    base_url, database_url, db_name = build_urls()

    print("Membuat database jika belum ada...")
    ensure_database_exists(base_url, db_name)

    print(f"Menerapkan migration dari: {migration_file}")
    apply_migration(database_url, migration_file)

    print("Migration selesai.")


if __name__ == "__main__":
    main()
