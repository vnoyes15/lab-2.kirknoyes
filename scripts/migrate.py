#!/usr/bin/env python3
"""Run all numbered SQL migrations in arx/db/migrations/ against DATABASE_URL, in order.

Section 86, S5: "Run python scripts/migrate.py — runs all numbered SQL migration files
in /arx/db/migrations/ in order against DATABASE_URL."

Usage:
    python scripts/migrate.py                  # production / Supabase-pointed DATABASE_URL
    python scripts/migrate.py --local-dev-shim  # local/CI Postgres only — also applies
                                                 # arx/db/local_dev/auth_shim.sql first
"""
import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "arx" / "db" / "migrations"
LOCAL_DEV_SHIM = REPO_ROOT / "arx" / "db" / "local_dev" / "auth_shim.sql"


def _migration_files() -> list[Path]:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise SystemExit(f"No migration files found in {MIGRATIONS_DIR}")
    return files


def _assert_not_supabase(database_url: str) -> None:
    host = urlparse(database_url).hostname or ""
    if host.endswith("supabase.co"):
        raise SystemExit(
            "Refusing to apply the local-dev auth shim against a Supabase database "
            f"({host}). Supabase already provides a real auth schema. Drop "
            "--local-dev-shim."
        )


def run(database_url: str, local_dev_shim: bool) -> None:
    if local_dev_shim:
        _assert_not_supabase(database_url)

    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            if local_dev_shim:
                print(f"Applying local dev auth shim: {LOCAL_DEV_SHIM.name}")
                cur.execute(LOCAL_DEV_SHIM.read_text())

            for path in _migration_files():
                print(f"Applying migration: {path.name}")
                cur.execute(path.read_text())

    print(f"Done — {len(_migration_files())} migrations applied.")


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--local-dev-shim",
        action="store_true",
        help="Also apply arx/db/local_dev/auth_shim.sql first (local/CI Postgres only).",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Defaults to the DATABASE_URL environment variable.",
    )
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL is not set (env var or --database-url).")

    run(args.database_url, args.local_dev_shim)
