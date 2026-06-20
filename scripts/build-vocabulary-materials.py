#!/usr/bin/env python3
"""Extract lesson vocabulary into level-level files in Materials/Vocabulary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
LESSONS_ROOT = REPO_ROOT / "Materials" / "Lessons"
VOCABULARY_ROOT = REPO_ROOT / "Materials" / "Vocabulary"
CURRICULUM_LEVELS = ("B1", "B2")


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source_file:
        return json.load(source_file)


def is_expression(value: str) -> bool:
    return any(character.isspace() for character in value.strip())


def extract_lesson(source: dict[str, Any]) -> dict[str, Any]:
    vocabulary = source["vocabulary_target"]
    active_items = vocabulary["active_words"]

    return {
        "lesson_id": source["id"],
        "course_position": source["course_position"],
        "vocabulary": {
            "theme": vocabulary["theme"],
            "words": [item for item in active_items if not is_expression(item)],
            "expressions": {
                "active": [item for item in active_items if is_expression(item)],
                "useful_chunks": vocabulary["useful_chunks"],
            },
            "usage_guidance": vocabulary["desired_presence"],
        },
    }


def build_level(curriculum_level: str) -> tuple[int, int]:
    source_directory = LESSONS_ROOT / curriculum_level / "Lesson_brief_JSONs"
    output_directory = VOCABULARY_ROOT / curriculum_level
    output_directory.mkdir(parents=True, exist_ok=True)

    lessons_by_stage: dict[int, list[dict[str, Any]]] = {}
    for source_path in sorted(source_directory.glob("*.json")):
        source = read_json(source_path)
        stage_number = source["course_position"]["stage"]
        lessons_by_stage.setdefault(stage_number, []).append(extract_lesson(source))

    for stale_path in output_directory.glob("*.json"):
        stale_path.unlink()

    extracted_stages = []
    lesson_count = 0
    for stage_number, lessons in sorted(lessons_by_stage.items()):
        lessons.sort(key=lambda lesson: lesson["course_position"]["absolute_day"])
        stage_names = {lesson["course_position"]["stage_name"] for lesson in lessons}
        if len(stage_names) != 1:
            raise ValueError(
                f"Expected one stage name for {curriculum_level} stage {stage_number}"
            )

        extracted_stages.append(
            {
                "number": stage_number,
                "name": stage_names.pop(),
                "lessons": lessons,
            }
        )
        lesson_count += len(lessons)

    extracted_level = {
        "curriculum_level": curriculum_level,
        "stages": extracted_stages,
    }
    output_path = output_directory / f"{curriculum_level}_Vocabulary.json"
    output_path.write_text(
        json.dumps(extracted_level, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return len(lessons_by_stage), lesson_count


def main() -> None:
    counts = {level: build_level(level) for level in CURRICULUM_LEVELS}
    summary = ", ".join(
        f"{level}: {stage_count} stages / {lesson_count} lessons"
        for level, (stage_count, lesson_count) in counts.items()
    )
    print(f"Generated vocabulary materials ({summary}).")


if __name__ == "__main__":
    main()
