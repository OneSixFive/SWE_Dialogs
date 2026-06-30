#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import DEFAULT_ENV_PATH, REPO_ROOT, _load_env_file
from app.db import Database


def default_database_path() -> Path:
    env_path = Path(os.environ.get("SVENSKA_ENV_PATH", DEFAULT_ENV_PATH))
    try:
        values = _load_env_file(env_path)
    except OSError:
        values = {}
    return Path(
        values.get("SVENSKA_DATABASE_PATH")
        or os.environ.get("SVENSKA_DATABASE_PATH")
        or REPO_ROOT / "backend" / "data" / "svenska.db"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill lesson_progress completion rows from completed lesson_sessions."
    )
    parser.add_argument(
        "--database-path",
        type=Path,
        default=None,
        help="SQLite database path. Defaults to SVENSKA_DATABASE_PATH or backend/data/svenska.db.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the repair. Without this flag, only prints a dry-run count.",
    )
    args = parser.parse_args()

    database_path = args.database_path or default_database_path()
    result = Database(database_path).backfill_lesson_progress_from_completed_sessions(apply=args.apply)
    payload = {
        "mode": "apply" if args.apply else "dry_run",
        "database_path": str(database_path),
        **result,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if result["remaining_count"] == 0 or not args.apply else 1


if __name__ == "__main__":
    raise SystemExit(main())
