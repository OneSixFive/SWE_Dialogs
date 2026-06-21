from __future__ import annotations

from typing import Any, Iterable

from .db import Database, VocabularyPracticeSession
from .learning_catalog import CatalogTarget, LearningCatalog, normalize_vocabulary_text


def build_lesson_evaluation_snapshot(
    *,
    database: Database,
    catalog: LearningCatalog,
    user_id: int,
    lesson_id: str,
    state: dict[str, Any],
    generated_lesson: dict[str, Any] | None,
    messages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    lesson = catalog.lesson(lesson_id)
    if lesson is None:
        return None

    authored = [*lesson.vocabulary_targets, *lesson.grammar_targets]
    candidate_map = {target.target_key: target.as_dict() for target in authored}
    evidence_text = normalize_vocabulary_text(
        " ".join(
            [str(message.get("content") or "") for message in messages]
            + [
                str(line.get("text") or "")
                for line in (generated_lesson or {}).get("dialogue", [])
                if isinstance(line, dict)
            ]
        )
    )
    for active in database.list_active_learning_targets(user_id=user_id, limit=100):
        key = str(active["target_key"])
        if active["target_kind"] != "vocabulary":
            continue
        if normalize_vocabulary_text(str(active["display_text"])) not in evidence_text:
            continue
        definition = catalog.target_definition(key)
        candidate_map[key] = definition.as_dict() if definition else _active_target_candidate(active)

    turns = _numbered_turns(messages)
    translation_attempts = state.get("translation_attempts") or []
    has_evidence = any(turn["role"] == "user" and turn["content"].strip() for turn in turns) or bool(
        translation_attempts
    )
    return {
        "evaluation_version": "v1",
        "source_kind": "lesson",
        "source_id": lesson_id,
        "source_context": {
            "lesson_payload": lesson.payload,
            "generated_lesson": generated_lesson,
            "translation_attempts": translation_attempts,
        },
        "candidates": list(candidate_map.values()),
        "turns": turns,
        "has_meaningful_evidence": has_evidence,
    }


def select_practice_targets(
    *,
    database: Database,
    catalog: LearningCatalog,
    user_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    completed_ids = database.completed_lesson_ids(user_id=user_id)
    progression = catalog.progression(completed_ids)
    eligible_lessons = catalog.eligible_lessons(progression, completed_ids)
    active = database.list_active_learning_targets(user_id=user_id, limit=100)
    recent_practices = database.list_vocabulary_practices(user_id=user_id, limit=2)
    recent_keys = {
        str(target["target_key"])
        for practice in recent_practices
        for target in practice.selection_snapshot.get("targets", [])
        if isinstance(target, dict) and target.get("target_key")
    }

    active_vocab = [_active_target_definition(item, catalog) for item in active if item["target_kind"] == "vocabulary"]
    active_grammar = [_active_target_definition(item, catalog) for item in active if item["target_kind"] == "grammar"]
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    _take_targets(selected, seen, active_vocab, 4, recent_keys=recent_keys, retain_high_priority=True)
    _take_targets(selected, seen, active_grammar, 1, recent_keys=recent_keys, retain_high_priority=True)

    fallback_vocab: list[dict[str, Any]] = []
    fallback_grammar: list[dict[str, Any]] = []
    current_stage = int(progression["stage_number"])
    current_level = str(progression["course_level"])
    ordered = sorted(
        eligible_lessons,
        key=lambda lesson: (
            lesson.course_level == current_level,
            lesson.stage_number == current_stage,
            lesson.absolute_day,
        ),
        reverse=True,
    )
    for lesson in ordered:
        fallback_vocab.extend(target.as_dict() for target in lesson.vocabulary_targets)
        fallback_grammar.extend(target.as_dict() for target in lesson.grammar_targets[:1])

    _take_targets(selected, seen, fallback_vocab, max(0, 4 - _kind_count(selected, "vocabulary")), recent_keys=recent_keys)
    _take_targets(selected, seen, fallback_grammar, max(0, 1 - _kind_count(selected, "grammar")), recent_keys=recent_keys)

    if len(selected) < 5:
        _take_targets(selected, seen, [*fallback_vocab, *fallback_grammar], 5 - len(selected), recent_keys=set())
    if len(selected) < 5:
        raise ValueError("Not enough eligible curriculum targets to generate a practice.")
    return progression, selected


def validate_vocabulary_quiz(quiz: dict[str, Any], selected_targets: list[dict[str, Any]]) -> None:
    questions = quiz.get("questions")
    if not isinstance(questions, list) or len(questions) != 5:
        raise ValueError("Vocabulary practice must contain exactly five questions.")
    selected_keys = {str(target["target_key"]) for target in selected_targets}
    ids: set[str] = set()
    covered_keys: set[str] = set()
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("Vocabulary question must be an object.")
        question_id = str(question.get("id") or "").strip()
        sentence = str(question.get("sentence_en") or "").strip()
        keys = question.get("target_keys")
        if not question_id or question_id in ids or not sentence:
            raise ValueError("Vocabulary questions need unique IDs and non-empty English sentences.")
        if not isinstance(keys, list) or not keys:
            raise ValueError("Every vocabulary question needs target attribution.")
        if any(str(key) not in selected_keys for key in keys):
            raise ValueError("Vocabulary question references an unselected target.")
        ids.add(question_id)
        covered_keys.update(str(key) for key in keys)
    if not selected_keys.issubset(covered_keys):
        raise ValueError("Every selected target must be exercised by the quiz.")


def vocabulary_interactor_context(practice: VocabularyPracticeSession) -> dict[str, Any]:
    if practice.quiz is None:
        raise ValueError("Vocabulary practice has no quiz.")
    index = int(practice.state.get("current_question_index", 0))
    questions = practice.quiz.get("questions") or []
    if not 0 <= index < len(questions):
        raise ValueError("Vocabulary practice has invalid current question.")
    return {
        "progression": practice.selection_snapshot.get("progression") or {},
        "selected_targets": practice.selection_snapshot.get("targets") or [],
        "quiz": practice.quiz,
        "prior_messages": practice.messages,
        "active_question": questions[index],
        "practice_state": practice.state,
    }


def validate_vocabulary_interaction(response: dict[str, Any]) -> None:
    if not str(response.get("assistant_text") or "").strip():
        raise ValueError("Vocabulary Interactor returned empty assistant text.")
    if response.get("turn_kind") not in {"answer_feedback", "free_form_chat"}:
        raise ValueError("Vocabulary Interactor returned invalid turn_kind.")
    if response.get("answer_assessment") not in {"correct", "partial", "incorrect", "not_an_answer"}:
        raise ValueError("Vocabulary Interactor returned invalid answer_assessment.")
    answered = bool(response.get("active_question_answered"))
    if response.get("turn_kind") == "free_form_chat" and answered:
        raise ValueError("Free-form chat cannot mark the active question answered.")
    if response.get("answer_assessment") == "not_an_answer" and answered:
        raise ValueError("A non-answer cannot mark the active question answered.")


def validate_evaluator_output(output: dict[str, Any], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    if output.get("evaluation_version") != "v1":
        raise ValueError("Evaluator returned an unsupported version.")
    results = output.get("results")
    if not isinstance(results, list):
        raise ValueError("Evaluator results must be a list.")
    candidates = {
        str(candidate["target_key"]): candidate
        for candidate in snapshot.get("candidates", [])
        if isinstance(candidate, dict) and candidate.get("target_key")
    }
    turn_ids = {
        str(turn["turn_id"])
        for turn in snapshot.get("turns", [])
        if isinstance(turn, dict) and turn.get("turn_id")
    }
    seen: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Evaluator result must be an object.")
        key = str(result.get("target_key") or "")
        if key not in candidates or key in seen:
            raise ValueError("Evaluator returned an unknown or duplicate target.")
        candidate = candidates[key]
        if result.get("target_kind") != candidate.get("target_kind"):
            raise ValueError("Evaluator target kind does not match the candidate.")
        if result.get("outcome") not in {"struggled", "partial", "demonstrated", "no_evidence"}:
            raise ValueError("Evaluator returned an invalid outcome.")
        if result.get("evidence_strength") not in {"production", "recognition", "assisted_production"}:
            raise ValueError("Evaluator returned invalid evidence strength.")
        confidence = result.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise ValueError("Evaluator confidence is outside 0...1.")
        evidence_ids = result.get("evidence_turn_ids")
        if not isinstance(evidence_ids, list) or any(str(value) not in turn_ids for value in evidence_ids):
            raise ValueError("Evaluator referenced evidence outside the snapshot.")
        result["reason"] = str(result.get("reason") or "")[:500]
        seen.add(key)
    if seen != set(candidates):
        raise ValueError("Evaluator must return every supplied candidate exactly once.")
    return results


def _numbered_turns(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for index, message in enumerate(messages[-200:], start=1):
        role = str(message.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        turns.append(
            {
                "turn_id": f"turn_{index}",
                "role": role,
                "content": str(message.get("content") or "")[:4000],
            }
        )
    return turns


def _active_target_candidate(active: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_kind": active["target_kind"],
        "target_key": active["target_key"],
        "display_text": active["display_text"],
        "target_subtype": active["target_subtype"],
        "source_level": active["source_level"],
        "lesson_id": None,
        "stage_number": None,
        "absolute_day": None,
        "description": None,
    }


def _active_target_definition(active: dict[str, Any], catalog: LearningCatalog) -> dict[str, Any]:
    definition = catalog.target_definition(str(active["target_key"]))
    candidate = definition.as_dict() if definition else _active_target_candidate(active)
    candidate["priority_score"] = float(active["priority_score"])
    candidate["success_streak"] = int(active["success_streak"])
    return candidate


def _take_targets(
    selected: list[dict[str, Any]],
    seen: set[str],
    candidates: Iterable[dict[str, Any]],
    count: int,
    *,
    recent_keys: set[str],
    retain_high_priority: bool = False,
) -> None:
    if count <= 0:
        return
    ordered = list(candidates)
    ordered.sort(
        key=lambda target: (
            str(target["target_key"]) in recent_keys
            and not (retain_high_priority and float(target.get("priority_score", 0)) >= 5),
            -float(target.get("priority_score", 0)),
        )
    )
    added = 0
    for target in ordered:
        key = str(target["target_key"])
        if key in seen:
            continue
        seen.add(key)
        selected.append(target)
        added += 1
        if added == count:
            break


def _kind_count(targets: list[dict[str, Any]], kind: str) -> int:
    return sum(1 for target in targets if target.get("target_kind") == kind)
