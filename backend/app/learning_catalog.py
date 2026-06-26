from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from .config import REPO_ROOT


MATERIALS_DIR = REPO_ROOT / "Materials"


def normalize_vocabulary_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.strip().split()).casefold()


def vocabulary_target_key(subtype: str, value: str) -> str:
    if subtype not in {"word", "expression"}:
        raise ValueError(f"Unsupported vocabulary subtype: {subtype}")
    return f"vocabulary:{subtype}:{normalize_vocabulary_text(value)}"


def grammar_code(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    ascii_value = "".join(character for character in normalized if not unicodedata.combining(character))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    if not slug:
        raise ValueError(f"Cannot derive grammar code from {value!r}")
    return f"grammar:{slug}"


@dataclass(frozen=True)
class CatalogTarget:
    target_kind: str
    target_key: str
    display_text: str
    target_subtype: str
    source_level: str
    lesson_id: str
    stage_number: int
    absolute_day: int
    description: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_kind": self.target_kind,
            "target_key": self.target_key,
            "display_text": self.display_text,
            "target_subtype": self.target_subtype,
            "source_level": self.source_level,
            "lesson_id": self.lesson_id,
            "stage_number": self.stage_number,
            "absolute_day": self.absolute_day,
            "description": self.description,
        }


@dataclass(frozen=True)
class CatalogLesson:
    lesson_id: str
    course_level: str
    stage_number: int
    week_number: int
    day_number: int
    absolute_day: int
    stage_name: str
    payload: dict[str, Any]
    vocabulary_targets: tuple[CatalogTarget, ...]
    grammar_targets: tuple[CatalogTarget, ...]


class LearningCatalog:
    def __init__(self, lessons: Iterable[CatalogLesson]) -> None:
        self.lessons = tuple(sorted(lessons, key=_lesson_sort_key))
        self.lessons_by_id = {lesson.lesson_id: lesson for lesson in self.lessons}
        self.lesson_order = {lesson.lesson_id: index for index, lesson in enumerate(self.lessons)}
        if len(self.lessons_by_id) != len(self.lessons):
            raise ValueError("Duplicate lesson IDs in learning catalog.")

        occurrences: dict[str, list[CatalogTarget]] = {}
        for lesson in self.lessons:
            for target in (*lesson.vocabulary_targets, *lesson.grammar_targets):
                occurrences.setdefault(target.target_key, []).append(target)
        self.target_occurrences = {key: tuple(value) for key, value in occurrences.items()}

    @classmethod
    def load(cls, materials_dir: Path = MATERIALS_DIR) -> LearningCatalog:
        vocabulary_by_lesson: dict[str, dict[str, Any]] = {}
        vocabulary_levels: dict[str, str] = {}
        for course_level in ("B1", "B2"):
            path = materials_dir / "Vocabulary" / course_level / f"{course_level}_Vocabulary.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            for stage in document.get("stages", []):
                for lesson in stage.get("lessons", []):
                    lesson_id = str(lesson["lesson_id"])
                    vocabulary_by_lesson[lesson_id] = lesson
                    vocabulary_levels[lesson_id] = course_level

        lessons: list[CatalogLesson] = []
        for path in sorted((materials_dir / "Lessons").rglob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            lesson_id = str(payload["id"])
            vocabulary_lesson = vocabulary_by_lesson.get(lesson_id)
            if vocabulary_lesson is None:
                raise ValueError(f"Vocabulary catalog is missing lesson {lesson_id}.")

            position = payload["course_position"]
            course_level = vocabulary_levels[lesson_id]
            stage_number = int(position["stage"])
            absolute_day = int(position["absolute_day"])
            vocabulary_targets = _vocabulary_targets(
                vocabulary_lesson,
                course_level=course_level,
                lesson_id=lesson_id,
                stage_number=stage_number,
                absolute_day=absolute_day,
            )
            grammar_targets = _grammar_targets(
                payload,
                course_level=course_level,
                lesson_id=lesson_id,
                stage_number=stage_number,
                absolute_day=absolute_day,
            )
            lessons.append(
                CatalogLesson(
                    lesson_id=lesson_id,
                    course_level=course_level,
                    stage_number=stage_number,
                    week_number=int(position["week"]),
                    day_number=int(position["day"]),
                    absolute_day=absolute_day,
                    stage_name=str(position.get("stage_name", "")),
                    payload=payload,
                    vocabulary_targets=vocabulary_targets,
                    grammar_targets=grammar_targets,
                )
            )

        if set(vocabulary_by_lesson) != {lesson.lesson_id for lesson in lessons}:
            missing = sorted(set(vocabulary_by_lesson) - {lesson.lesson_id for lesson in lessons})
            raise ValueError(f"Lesson catalog is missing vocabulary lessons: {missing[:5]}")
        return cls(lessons)

    def lesson(self, lesson_id: str) -> CatalogLesson | None:
        return self.lessons_by_id.get(lesson_id)

    def progression(self, completed_lesson_ids: set[str]) -> dict[str, Any]:
        current = next(
            (lesson for lesson in self.lessons if lesson.lesson_id not in completed_lesson_ids),
            self.lessons[-1],
        )
        return {
            "course_level": current.course_level,
            "stage_number": current.stage_number,
            "stage_name": current.stage_name,
            "current_lesson_id": current.lesson_id,
            "progress_cutoff_absolute_day": current.absolute_day,
        }

    def eligible_lessons(self, progression: dict[str, Any], completed_lesson_ids: set[str]) -> list[CatalogLesson]:
        current_id = str(progression["current_lesson_id"])
        current_index = self.lesson_order[current_id]
        eligible_ids = {*completed_lesson_ids, current_id}
        return [
            lesson
            for index, lesson in enumerate(self.lessons)
            if index <= current_index and lesson.lesson_id in eligible_ids
        ]

    def target_definition(self, target_key: str) -> CatalogTarget | None:
        occurrences = self.target_occurrences.get(target_key)
        return occurrences[0] if occurrences else None

    def vocabulary_definitions(self) -> list[CatalogTarget]:
        definitions: list[CatalogTarget] = []
        for occurrences in self.target_occurrences.values():
            if occurrences and occurrences[0].target_kind == "vocabulary":
                definitions.append(occurrences[0])
        return definitions

    def target_occurrence_count(self, target_key: str) -> int:
        return len(self.target_occurrences.get(target_key) or ())


@lru_cache(maxsize=1)
def get_learning_catalog() -> LearningCatalog:
    return LearningCatalog.load()


def _lesson_sort_key(lesson: CatalogLesson) -> tuple[int, int, int, int, int]:
    return (
        0 if lesson.course_level == "B1" else 1,
        lesson.stage_number,
        lesson.week_number,
        lesson.day_number,
        lesson.absolute_day,
    )


def _vocabulary_targets(
    vocabulary_lesson: dict[str, Any],
    *,
    course_level: str,
    lesson_id: str,
    stage_number: int,
    absolute_day: int,
) -> tuple[CatalogTarget, ...]:
    vocabulary = vocabulary_lesson.get("vocabulary") or {}
    values: list[tuple[str, str]] = [("word", str(value)) for value in vocabulary.get("words", [])]
    expressions = vocabulary.get("expressions") or {}
    values.extend(("expression", str(value)) for value in expressions.get("active", []))
    values.extend(("expression", str(value)) for value in expressions.get("useful_chunks", []))

    targets: list[CatalogTarget] = []
    seen: set[str] = set()
    for subtype, display_text in values:
        key = vocabulary_target_key(subtype, display_text)
        if key in seen:
            continue
        seen.add(key)
        targets.append(
            CatalogTarget(
                target_kind="vocabulary",
                target_key=key,
                display_text=display_text,
                target_subtype=subtype,
                source_level=course_level,
                lesson_id=lesson_id,
                stage_number=stage_number,
                absolute_day=absolute_day,
                description=str(vocabulary.get("theme") or "") or None,
            )
        )
    return tuple(targets)


def _grammar_targets(
    payload: dict[str, Any],
    *,
    course_level: str,
    lesson_id: str,
    stage_number: int,
    absolute_day: int,
) -> tuple[CatalogTarget, ...]:
    grammar = payload.get("grammar_target") or {}
    main = grammar.get("main_focus") or {}
    values: list[tuple[str, str | None]] = []
    if main.get("name"):
        values.append((str(main["name"]), str(main.get("description") or "") or None))
    values.extend((str(value), None) for value in grammar.get("allowed_supporting_grammar", [])[:4])

    targets: list[CatalogTarget] = []
    seen: set[str] = set()
    for index, (display_text, description) in enumerate(values):
        key = grammar_code(display_text)
        if key in seen:
            continue
        seen.add(key)
        targets.append(
            CatalogTarget(
                target_kind="grammar",
                target_key=key,
                display_text=display_text,
                target_subtype="main" if index == 0 else "supporting",
                source_level=course_level,
                lesson_id=lesson_id,
                stage_number=stage_number,
                absolute_day=absolute_day,
                description=description,
            )
        )
    return tuple(targets)
