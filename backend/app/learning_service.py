from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from .db import Database, VocabularyPracticeSession
from .learning_catalog import CatalogTarget, LearningCatalog, normalize_vocabulary_text, vocabulary_target_key


LOOKUP_DEFAULT_VOCABULARY_SLOTS = 2
LOOKUP_MAX_VOCABULARY_SLOTS = 3
LOOKUP_HIGH_PRIORITY_THRESHOLD = 6.0
DIRECT_LOOKUP_PRIORITY = 6.0
SENTENCE_LOOKUP_PRIORITY = 4.0
AD_HOC_LOOKUP_PRIORITY = 1.0
REPEATED_LOOKUP_PRIORITY_BONUS = 1.5
MAX_LOOKUP_CANDIDATES = 3
MAX_AD_HOC_LOOKUP_CHARS = 64
MAX_AD_HOC_LOOKUP_WORDS = 4

_BASIC_SENTENCE_WORDS = {
    "att",
    "det",
    "du",
    "en",
    "ett",
    "han",
    "hon",
    "hur",
    "i",
    "idag",
    "jag",
    "och",
    "på",
    "som",
    "är",
}


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
        "evaluation_version": "v3",
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

    active_vocab_all = [_active_target_definition(item, catalog) for item in active if item["target_kind"] == "vocabulary"]
    active_lookup_vocab = [target for target in active_vocab_all if _is_lookup_target(target)]
    active_vocab = [target for target in active_vocab_all if not _is_lookup_target(target)]
    active_grammar = [_active_target_definition(item, catalog) for item in active if item["target_kind"] == "grammar"]
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    _take_targets(
        selected,
        seen,
        active_lookup_vocab,
        LOOKUP_DEFAULT_VOCABULARY_SLOTS,
        recent_keys=recent_keys,
        retain_high_priority=True,
    )
    high_priority_lookup = [
        target for target in active_lookup_vocab if float(target.get("priority_score", 0)) >= LOOKUP_HIGH_PRIORITY_THRESHOLD
    ]
    _take_targets(
        selected,
        seen,
        high_priority_lookup,
        LOOKUP_MAX_VOCABULARY_SLOTS - _kind_count(selected, "vocabulary"),
        recent_keys=recent_keys,
        retain_high_priority=True,
    )
    _take_targets(
        selected,
        seen,
        active_vocab,
        max(0, 4 - _kind_count(selected, "vocabulary")),
        recent_keys=recent_keys,
        retain_high_priority=True,
    )
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
    expected_version = snapshot.get("evaluation_version", "v1")
    if output.get("evaluation_version") != expected_version or expected_version not in {"v1", "v2", "v3"}:
        raise ValueError("Evaluator returned an unsupported version.")

    if expected_version == "v3":
        checked_target_keys = output.get("checked_target_keys")
        if not isinstance(checked_target_keys, list) or any(
            not isinstance(key, str) or not key for key in checked_target_keys
        ):
            raise ValueError("Evaluator checked_target_keys must be a list of target keys.")
        results = output.get("updates")
    else:
        checked_target_keys = None
        results = output.get("results")
    if not isinstance(results, list):
        raise ValueError("Evaluator updates/results must be a list.")
    candidates = {
        str(candidate["target_key"]): candidate
        for candidate in snapshot.get("candidates", [])
        if isinstance(candidate, dict) and candidate.get("target_key")
    }
    if expected_version == "v3":
        assert checked_target_keys is not None
        if len(checked_target_keys) != len(set(checked_target_keys)):
            raise ValueError("Evaluator checked_target_keys contains duplicates.")
        if set(checked_target_keys) != set(candidates):
            raise ValueError("Evaluator must check every supplied candidate exactly once.")
    turn_ids = {
        str(turn["turn_id"])
        for turn in snapshot.get("turns", [])
        if isinstance(turn, dict) and turn.get("turn_id")
    }
    lookup_ids = {
        str(lookup["lookup_id"])
        for lookup in snapshot.get("lookup_events", [])
        if isinstance(lookup, dict) and lookup.get("lookup_id")
    }
    tracked_keys = {
        str(key)
        for key, value in (snapshot.get("current_user_state") or {}).items()
        if isinstance(value, dict)
    }
    seen: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Evaluator result must be an object.")
        key = str(result.get("target_key") or "")
        if key not in candidates or key in seen:
            raise ValueError("Evaluator returned an unknown or duplicate target.")
        candidate = candidates[key]
        if expected_version != "v3" and result.get("target_kind") != candidate.get("target_kind"):
            raise ValueError("Evaluator target kind does not match the candidate.")
        outcome = result.get("outcome")
        if outcome not in {"struggled", "partial", "demonstrated", "no_evidence", "lookup_requested"}:
            raise ValueError("Evaluator returned an invalid outcome.")
        if expected_version == "v3":
            if outcome == "no_evidence":
                raise ValueError("Evaluator v3 must omit no_evidence updates.")
            if outcome == "demonstrated" and key not in tracked_keys:
                raise ValueError("Evaluator v3 must omit demonstrated updates for untracked targets.")
        evidence_strength = result.get("evidence_strength")
        if outcome == "lookup_requested":
            if snapshot.get("source_kind") != "translation_lookup":
                raise ValueError("Evaluator returned lookup evidence for a non-lookup source.")
            if candidate.get("target_kind") != "vocabulary":
                raise ValueError("Evaluator returned lookup evidence for a non-vocabulary target.")
            if evidence_strength != "lookup":
                raise ValueError("Evaluator returned invalid lookup evidence strength.")
            evidence_lookup_ids = result.get("evidence_lookup_ids")
            if not isinstance(evidence_lookup_ids, list) or any(str(value) not in lookup_ids for value in evidence_lookup_ids):
                raise ValueError("Evaluator referenced lookup evidence outside the snapshot.")
            if expected_version == "v3" and not evidence_lookup_ids:
                raise ValueError("Evaluator v3 lookup updates require evidence lookup IDs.")
        elif evidence_strength not in {"production", "recognition", "assisted_production"}:
            raise ValueError("Evaluator returned invalid evidence strength.")
        confidence = result.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise ValueError("Evaluator confidence is outside 0...1.")
        evidence_ids = result.get("evidence_turn_ids")
        if evidence_ids is None and expected_version == "v3" and snapshot.get("source_kind") == "translation_lookup":
            evidence_ids = []
        if not isinstance(evidence_ids, list) or any(str(value) not in turn_ids for value in evidence_ids):
            raise ValueError("Evaluator referenced evidence outside the snapshot.")
        if expected_version == "v3" and outcome != "lookup_requested" and not evidence_ids:
            raise ValueError("Evaluator v3 updates require evidence turn IDs.")
        result["reason"] = str(result.get("reason") or "")[:500]
        seen.add(key)
    if expected_version != "v3" and seen != set(candidates):
        raise ValueError("Evaluator must return every supplied candidate exactly once.")
    return results


def build_translation_lookup_evaluation_snapshot(
    *,
    database: Database,
    catalog: LearningCatalog,
    user_id: int,
    lookup_event: dict[str, Any],
) -> dict[str, Any] | None:
    candidates = resolve_translation_lookup_candidates(
        database=database,
        catalog=catalog,
        user_id=user_id,
        selected_text=str(lookup_event["selected_text"]),
        surrounding_text=lookup_event.get("surrounding_text"),
    )
    if not candidates:
        return None
    lookup_id = f"lookup_{lookup_event['id']}"
    return {
        "evaluation_version": "v3",
        "source_kind": "translation_lookup",
        "source_id": f"translation_lookup:{lookup_event['id']}",
        "source_context": {
            "source_kind": lookup_event.get("source_kind"),
            "source_id": lookup_event.get("source_id"),
            "source_surface": lookup_event.get("source_surface"),
            "visible_course_level": lookup_event.get("visible_course_level"),
        },
        "candidates": candidates,
        "lookup_events": [
            {
                "lookup_id": lookup_id,
                "selected_text": lookup_event["selected_text"],
                "source_kind": lookup_event.get("source_kind"),
                "source_id": lookup_event.get("source_id"),
                "source_surface": lookup_event.get("source_surface"),
                "surrounding_text": lookup_event.get("surrounding_text"),
            }
        ],
        "has_meaningful_evidence": True,
    }


def resolve_translation_lookup_candidates(
    *,
    database: Database,
    catalog: LearningCatalog,
    user_id: int,
    selected_text: str,
    surrounding_text: str | None = None,
) -> list[dict[str, Any]]:
    selected_match = _lookup_match_text(selected_text)
    if not selected_match:
        return []

    definitions = catalog.vocabulary_definitions()
    exact_matches = [
        definition
        for definition in definitions
        if _lookup_match_text(definition.display_text) == selected_match
    ]
    if exact_matches:
        candidates = [
            _lookup_candidate(
                definition,
                catalog=catalog,
                lookup_kind="direct",
                selected_text=selected_text,
                surrounding_text=surrounding_text,
            )
            for definition in exact_matches
        ]
        return _rank_lookup_candidates(candidates)[:MAX_LOOKUP_CANDIDATES]

    selected_words = selected_match.split()
    sentence_like = (
        len(selected_words) >= MAX_AD_HOC_LOOKUP_WORDS
        or len(selected_text.strip()) > MAX_AD_HOC_LOOKUP_CHARS
        or any(mark in selected_text for mark in ".?!")
    )
    if sentence_like:
        candidates = []
        padded_selected = f" {selected_match} "
        for definition in definitions:
            target_match = _lookup_match_text(definition.display_text)
            if not target_match or f" {target_match} " not in padded_selected:
                continue
            if definition.target_subtype == "word" and target_match in _BASIC_SENTENCE_WORDS:
                continue
            candidates.append(
                _lookup_candidate(
                    definition,
                    catalog=catalog,
                    lookup_kind="sentence",
                    selected_text=selected_text,
                    surrounding_text=surrounding_text,
                )
            )
        return _rank_lookup_candidates(candidates)[:MAX_LOOKUP_CANDIDATES]

    if not _plausible_ad_hoc_lookup(selected_match):
        return []
    target_key = vocabulary_target_key("word", selected_match)
    existing = catalog.target_definition(target_key)
    if existing is not None:
        return [
            _lookup_candidate(
                existing,
                catalog=catalog,
                lookup_kind="direct",
                selected_text=selected_text,
                surrounding_text=surrounding_text,
            )
        ]
    prior = database.learning_target_states(user_id=user_id, target_keys=[target_key]).get(target_key)
    repeat_bonus = REPEATED_LOOKUP_PRIORITY_BONUS if prior and int(prior.get("evidence_count", 0)) > 0 else 0.0
    return [
        {
            "target_kind": "vocabulary",
            "target_key": target_key,
            "display_text": selected_text.strip(),
            "target_subtype": "word",
            "source_level": "lookup",
            "lesson_id": None,
            "stage_number": None,
            "absolute_day": None,
            "description": "Manual translation lookup",
            "selection_origin": "manual_translation_lookup",
            "lookup_context": surrounding_text or selected_text.strip(),
            "lookup_priority_delta": AD_HOC_LOOKUP_PRIORITY + repeat_bonus,
            "priority_reason": "Manual translation lookup for a non-catalog word.",
        }
    ]


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
    if active.get("latest_evidence_outcome"):
        candidate["latest_evidence_outcome"] = active.get("latest_evidence_outcome")
    if active.get("latest_evidence_json"):
        candidate["latest_evidence"] = active.get("latest_evidence_json")
    if _is_lookup_target(active):
        candidate["selection_origin"] = "manual_translation_lookup"
    return candidate


def _is_lookup_target(target: dict[str, Any]) -> bool:
    return (
        target.get("latest_evidence_outcome") == "lookup_requested"
        or target.get("selection_origin") == "manual_translation_lookup"
    )


def _lookup_candidate(
    definition: CatalogTarget,
    *,
    catalog: LearningCatalog,
    lookup_kind: str,
    selected_text: str,
    surrounding_text: str | None,
) -> dict[str, Any]:
    candidate = definition.as_dict()
    occurrence_count = catalog.target_occurrence_count(definition.target_key)
    commonness_boost = min(2.0, max(0.0, float(occurrence_count - 1) * 0.5))
    subtype_boost = 1.0 if definition.target_subtype == "expression" else 0.0
    level_boost = 0.75 if definition.source_level == "B1" else 0.25
    base = DIRECT_LOOKUP_PRIORITY if lookup_kind == "direct" else SENTENCE_LOOKUP_PRIORITY
    candidate["selection_origin"] = "manual_translation_lookup"
    candidate["lookup_context"] = surrounding_text or selected_text.strip()
    candidate["lookup_priority_delta"] = base + commonness_boost + subtype_boost + level_boost
    candidate["priority_reason"] = (
        "Manual translation lookup of a known vocabulary target."
        if lookup_kind == "direct"
        else "Manual translation lookup of a sentence containing this vocabulary target."
    )
    candidate["lookup_occurrence_count"] = occurrence_count
    candidate["lookup_match_kind"] = lookup_kind
    return candidate


def _rank_lookup_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = list(candidates)
    ordered.sort(
        key=lambda candidate: (
            -float(candidate.get("lookup_priority_delta", 0)),
            0 if candidate.get("target_subtype") == "expression" else 1,
            -len(str(candidate.get("display_text") or "")),
            str(candidate.get("target_key") or ""),
        )
    )
    return ordered


def _lookup_match_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    characters = [character if character.isalnum() else " " for character in normalized]
    return " ".join("".join(characters).split())


def _plausible_ad_hoc_lookup(value: str) -> bool:
    if not value or len(value) > MAX_AD_HOC_LOOKUP_CHARS:
        return False
    words = value.split()
    if not words or len(words) > MAX_AD_HOC_LOOKUP_WORDS:
        return False
    if any(re.search(r"\d", word) for word in words):
        return False
    return any(any(character in "åäöabcdefghijklmnopqrstuvwxyz" for character in word) for word in words)


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
