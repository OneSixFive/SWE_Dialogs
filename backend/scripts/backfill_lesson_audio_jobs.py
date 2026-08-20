from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from app.config import load_settings
from app.db import Database


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue durable audio jobs for recent active users.")
    parser.add_argument("--active-days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true", help="Queue jobs. Without this flag, only print candidates.")
    args = parser.parse_args()

    settings = load_settings()
    database = Database(settings.database_path)
    active_since = (datetime.now(UTC) - timedelta(days=max(args.active_days, 0))).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    candidates = database.list_missing_lesson_audio_candidates(
        active_since=active_since,
        limit=max(args.limit, 0),
    )
    queued = 0
    skipped = 0
    for user_id, lesson_id in candidates:
        if not args.apply:
            print(f"candidate user_id={user_id} lesson_id={lesson_id}")
            continue
        try:
            job, audio = database.request_lesson_audio_job(
                user_id=user_id,
                lesson_id=lesson_id,
                max_queued_per_user=settings.lesson_audio_max_queued_per_user,
                retry_cooldown_seconds=0,
            )
            queued += int(job is not None and audio is None)
        except (ValueError, OverflowError):
            skipped += 1
    print(f"candidates={len(candidates)} queued={queued} skipped={skipped} applied={args.apply}")


if __name__ == "__main__":
    main()
