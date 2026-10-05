"""Load the cleaned CSV tables into PostgreSQL and (re)create the KPI views.

Usage:  python -m src.load_to_db [--no-views]

Steps (all inside one transaction, so a failed run leaves the previous state intact):
  1. run sql/schema.sql   (drops and recreates the ``service_ops`` schema)
  2. COPY every cleaned CSV in foreign-key order
  3. run sql/views.sql
  4. print and verify row counts against the CSV files
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import psycopg
from psycopg import sql

from src.config import CLEAN_DIR
from src.db import DB_SCHEMA, SQL_DIR, DbSettings, connect, load_settings

# Parents before children so foreign keys are satisfied during the load.
LOAD_ORDER: tuple[str, ...] = (
    "customers", "service_centers", "technicians", "vehicles", "appointments",
    "work_orders", "parts", "part_usage", "financials", "feedback",
)
CHUNK_BYTES = 1 << 20


def run_sql_file(conn: psycopg.Connection, path: Path) -> None:
    """Execute a (multi-statement) SQL script."""
    conn.execute(path.read_text(encoding="utf-8"))


def csv_columns(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as fh:
        return next(csv.reader(fh))


def csv_row_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as fh:
        return sum(1 for _ in csv.reader(fh)) - 1  # minus header


def copy_csv(conn: psycopg.Connection, table: str, path: Path) -> None:
    """Bulk-load one CSV with COPY; the CSV header supplies the column list."""
    columns = sql.SQL(", ").join(sql.Identifier(c) for c in csv_columns(path))
    stmt = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true)").format(sql.Identifier(table), columns)
    with conn.cursor() as cur, cur.copy(stmt) as copy, path.open("rb") as fh:
        while chunk := fh.read(CHUNK_BYTES):
            copy.write(chunk)


def load_all(conn: psycopg.Connection, clean_dir: Path = CLEAN_DIR) -> None:
    for table in LOAD_ORDER:
        path = clean_dir / f"{table}.csv"
        if not path.exists():
            raise SystemExit(f"Missing cleaned file {path}. Run `python -m src.data_cleaning` first.")
        copy_csv(conn, table, path)


def table_counts(conn: psycopg.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in LOAD_ORDER:
        row = conn.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))).fetchone()
        counts[table] = int(row[0]) if row else 0
    return counts


def verify_counts(counts: dict[str, int], clean_dir: Path = CLEAN_DIR) -> bool:
    """Print a table-vs-CSV comparison; return True when every table matches."""
    print(f"\n{'table':<18}{'csv rows':>10}{'db rows':>10}  status")
    ok = True
    for table in LOAD_ORDER:
        expected = csv_row_count(clean_dir / f"{table}.csv")
        match = counts[table] == expected
        ok &= match
        print(f"{table:<18}{expected:>10,}{counts[table]:>10,}  {'OK' if match else 'MISMATCH'}")
    return ok


def list_views(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.views WHERE table_schema = %s ORDER BY 1", (DB_SCHEMA,)
    ).fetchall()
    return [r[0] for r in rows]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load cleaned CSVs into PostgreSQL and create KPI views.")
    parser.add_argument("--no-views", action="store_true", help="skip sql/views.sql")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings: DbSettings = load_settings()
    print(f"Connecting to {settings.display} ...")
    with connect(settings) as conn:  # one transaction: commit on success, rollback on error
        print("Applying sql/schema.sql ...")
        run_sql_file(conn, SQL_DIR / "schema.sql")
        print("Loading cleaned CSVs (COPY) ...")
        load_all(conn)
        if not args.no_views:
            print("Creating views from sql/views.sql ...")
            run_sql_file(conn, SQL_DIR / "views.sql")
        counts = table_counts(conn)
        views = [] if args.no_views else list_views(conn)
        ok = verify_counts(counts)
        if not ok:
            conn.rollback()  # keep the previously loaded data rather than committing a partial load
    if views:
        print(f"\nViews ({len(views)}): " + ", ".join(views))
    print("\nLoad complete." if ok else "\nRow-count mismatches: load rolled back, previous data kept.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
