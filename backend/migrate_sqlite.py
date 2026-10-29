"""Migrate a local SpendFlow / Tally SQLite database to an EMPTY PostgreSQL DB.

Usage:
  DATABASE_URL='postgresql://...' python -m backend.migrate_sqlite --source /path/to/tally.db

Run with the app stopped. Make an offline copy/backup first. Never upload the
SQLite database or passwords to GitHub. This utility copies relational data
(including password hashes), but source PDF files need separate migration.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

from .postgres import init_postgres, pool
from .db import SCHEMA

TABLES = [
    "users", "sessions", "password_reset_tokens", "accounts", "categories",
    "statements", "transactions", "splits", "merchant_rules",
    "import_exclusions", "classification_rules", "transaction_groups",
    "transaction_group_members", "exclusion_rules", "flow_groups",
    "flow_group_members", "people", "people_upi", "people_transactions",
    "budgets", "goals",
]


def existing_tables(db):
    return {
        row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def run(source: Path, apply: bool):
    if not source.is_file():
        raise SystemExit(f"SQLite source does not exist: {source}")
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("Set DATABASE_URL for the destination PostgreSQL database")
    src = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        issue = src.execute("PRAGMA integrity_check").fetchone()[0]
        if issue != "ok":
            raise SystemExit(f"Source SQLite integrity check failed: {issue}")
        original = existing_tables(src)
        counts = {table: src.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                  for table in TABLES if table in original}
        print("SOURCE COUNTS:", json.dumps(counts, sort_keys=True))
        if not apply:
            print("DRY RUN ONLY. To copy data pass --apply after backing up your database.")
            return
        init_postgres(SCHEMA)
        with pool().connection() as dest:
            with dest.transaction():
                for table in TABLES:
                    if table not in original:
                        continue
                    n = dest.execute(f'SELECT count(*) FROM "{table}"').fetchone()["count"]
                    if n:
                        raise ValueError(f"Destination table {table} already contains {n} rows; refusing to overwrite")
                # Keep all inserted IDs, so relationships survive unchanged.
                dest.execute("SET CONSTRAINTS ALL DEFERRED")
                for table in TABLES:
                    if table not in original:
                        continue
                    rows = src.execute(f'SELECT * FROM "{table}"')
                    cols = [item[0] for item in rows.description]
                    if not cols:
                        continue
                    dest_cols = {row["column_name"] for row in dest.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema=current_schema() AND table_name=%s", (table,))}
                    cols = [name for name in cols if name in dest_cols]
                    placeholders = ",".join("%s" for _ in cols)
                    col_names = ",".join('"' + name + '"' for name in cols)
                    statement = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})'
                    batch = []
                    for row in rows:
                        batch.append(tuple(row[name] for name in cols))
                        if len(batch) >= 500:
                            with dest.cursor() as cur:
                                cur.executemany(statement, batch)
                            batch.clear()
                    if batch:
                        with dest.cursor() as cur:
                            cur.executemany(statement, batch)
                    imported = dest.execute(f'SELECT count(*) AS n FROM "{table}"').fetchone()["n"]
                    if imported != counts[table]:
                        raise ValueError(f"Mismatch in {table}: expected {counts[table]}, got {imported}")
                    print(f"Verified {table}: {imported}")
                    if "id" in cols:
                        dest.execute(
                            "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                            "GREATEST((SELECT COALESCE(MAX(id),0) FROM " + '"' + table + '"' +
                            "), 1), (SELECT COUNT(*)>0 FROM " + '"' + table + '"' + "))",
                            (table,),
                        )
                # Verify integrity and key business totals before commit.
                checks = [
                    ("transactions", "SELECT COALESCE(SUM(amount_minor),0) FROM transactions"),
                    ("transactions", "SELECT COUNT(*) FROM transactions WHERE status='categorized'"),
                    ("accounts", "SELECT COUNT(*) FROM accounts"),
                    ("users", "SELECT COUNT(*) FROM users"),
                ]
                for table, query in checks:
                    if table in original:
                        a = src.execute(query).fetchone()[0]
                        b = list(dest.execute(query).fetchone().values())[0]
                        if a != b:
                            raise ValueError(f"Financial reconciliation failed for {query}: {a} != {b}")
                print("Financial reconciliation passed; committing migration")
        print("SUCCESS. Keep the SQLite source backup. Migrate uploaded files separately.")
    finally:
        src.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    run(args.source, args.apply)
