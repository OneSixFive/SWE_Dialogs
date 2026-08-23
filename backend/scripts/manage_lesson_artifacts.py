#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import REPO_ROOT
from app.db import Database


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run-first invalidation and private-artifact garbage collection."
    )
    parser.add_argument("--database", type=Path, default=REPO_ROOT / "backend/data/svenska.db")
    parser.add_argument(
        "--audio-directory", type=Path, default=REPO_ROOT / "backend/data/shared_lesson_audio"
    )
    parser.add_argument("--invalidate-artifact-id")
    parser.add_argument("--reason", default="manual invalidation")
    parser.add_argument("--gc-private-older-than-days", type=int)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.invalidate_artifact_id and args.gc_private_older_than_days is None:
        parser.error("Choose --invalidate-artifact-id or --gc-private-older-than-days.")
    if args.gc_private_older_than_days is not None and args.gc_private_older_than_days < 1:
        parser.error("--gc-private-older-than-days must be at least 1.")

    database = Database(args.database)
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"Mode: {mode}")

    if args.invalidate_artifact_id:
        artifact = database.get_lesson_artifact(args.invalidate_artifact_id)
        if artifact is None:
            print(f"Artifact not found: {args.invalidate_artifact_id}")
        else:
            print(
                f"Invalidate artifact={artifact.id} lesson={artifact.lesson_id} "
                f"scope={artifact.scope} reason={args.reason!r}"
            )
            if args.apply:
                changed = database.invalidate_lesson_artifact(
                    artifact_id=artifact.id, reason=args.reason
                )
                print(f"Invalidated: {changed}")

    if args.gc_private_older_than_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=args.gc_private_older_than_days)
        cutoff_text = cutoff.isoformat(timespec="microseconds").replace("+00:00", "Z")
        candidates = database.unreferenced_private_artifacts(
            created_before=cutoff_text, limit=args.limit
        )
        print(f"Private GC candidates before {cutoff_text}: {len(candidates)}")
        audio_root = args.audio_directory.resolve()
        for artifact in candidates:
            print(f"  artifact={artifact.id} lesson={artifact.lesson_id} created={artifact.created_at}")
            if not args.apply:
                continue
            paths = database.delete_unreferenced_private_artifact(artifact_id=artifact.id)
            for relative_path in paths:
                target = (audio_root / relative_path).resolve()
                try:
                    target.relative_to(audio_root)
                except ValueError:
                    print(f"  refused unsafe audio path: {relative_path}")
                    continue
                if target.is_file():
                    target.unlink()
                    print(f"  deleted audio: {relative_path}")


if __name__ == "__main__":
    main()
