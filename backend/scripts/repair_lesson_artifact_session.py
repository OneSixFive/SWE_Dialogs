#!/usr/bin/env python3
from __future__ import annotations

import argparse

from app.config import load_settings
from app.db import Database
from app.lesson_artifacts import artifact_audio_identity


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run-first repair for a private lesson artifact orphaned before session attachment."
    )
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--lesson-id", required=True)
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--expected-current-artifact-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    database = Database(settings.database_path)
    artifact = database.get_lesson_artifact(args.artifact_id)
    session = database.get_lesson_session(user_id=args.user_id, lesson_id=args.lesson_id)
    if artifact is None:
        raise SystemExit("Artifact not found.")
    if artifact.scope != "private" or artifact.owner_user_id != args.user_id:
        raise SystemExit("Artifact is not private and owned by the requested user.")
    if artifact.lesson_id != args.lesson_id:
        raise SystemExit("Artifact lesson does not match.")
    if session is None:
        raise SystemExit("Lesson session not found.")
    if session.lesson_artifact_id not in {args.expected_current_artifact_id, args.artifact_id}:
        raise SystemExit("Session no longer references the expected current artifact.")

    dialogue_hash, content_hash, recipe = artifact_audio_identity(
        settings, artifact.generated_lesson
    )
    print(
        f"mode={'APPLY' if args.apply else 'DRY RUN'} user_id={args.user_id} "
        f"lesson_id={args.lesson_id} current_artifact={session.lesson_artifact_id} "
        f"replacement_artifact={artifact.id} audio_hash={content_hash[:12]}"
    )
    if not args.apply:
        return

    repaired, audio_job = database.repair_attach_private_artifact(
        user_id=args.user_id,
        lesson_id=args.lesson_id,
        artifact_id=artifact.id,
        expected_current_artifact_id=args.expected_current_artifact_id,
        dialogue_text_hash=dialogue_hash,
        audio_content_hash=content_hash,
        audio_recipe_fingerprint=recipe.fingerprint,
        audio_model=settings.lesson_tts_model,
        voice_config_version=settings.lesson_tts_voice_config_version,
    )
    print(
        f"repaired session_artifact={repaired.lesson_artifact_id} "
        f"session_state={repaired.status} audio_job_id={audio_job.id} "
        f"audio_job_status={audio_job.status}"
    )


if __name__ == "__main__":
    main()
