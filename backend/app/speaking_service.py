from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import REPO_ROOT
from .learning_catalog import CatalogLesson


SPEAKER_PROMPT_PATH = REPO_ROOT / "Materials" / "Speaker_prompt.md"
SPEAKER_TARGET_REPLIES = 10
SPEAKER_LEARNER_TURNS = frozenset(
    {"opening", "substantive", "correction_repeat", "help_or_clarification", "unclear"}
)
EXPECTED_DIALOGUE_LINE_COUNT = 20
MAX_DIALOGUE_LINE_CHARACTERS = 800
MAX_DIALOGUE_TOTAL_UTF8_BYTES = 12_000
MAX_GENERATED_LESSON_JSON_UTF8_BYTES = 64_000


class SpeakingContextError(ValueError):
    pass


def _required_lesson_text(payload: dict[str, Any], *path: str) -> str:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            raise SpeakingContextError(
                f"Speaking lesson context is missing {'.'.join(path)}."
            )
        current = current[key]
    if not isinstance(current, str) or not current.strip():
        raise SpeakingContextError(
            f"Speaking lesson context has invalid {'.'.join(path)}."
        )
    return current.strip()


def project_speaking_lesson_context(lesson: CatalogLesson) -> dict[str, Any]:
    payload = lesson.payload
    return {
        "id": lesson.lesson_id,
        "difficulty": _required_lesson_text(payload, "dialogue_task", "difficulty"),
        "communicative_goal": _required_lesson_text(
            payload, "lesson_intent", "communicative_function"
        ),
        "scenario": _required_lesson_text(payload, "dialogue_task", "scenario"),
        "grammar_focus": {
            "name": _required_lesson_text(
                payload, "grammar_target", "main_focus", "name"
            ),
            "description": _required_lesson_text(
                payload, "grammar_target", "main_focus", "description"
            ),
        },
        "rough_structure": {
            "opening": _required_lesson_text(payload, "dialogue_shape", "opening"),
            "middle": _required_lesson_text(payload, "dialogue_shape", "middle"),
            "ending": _required_lesson_text(payload, "dialogue_shape", "ending"),
        },
    }


def project_reference_dialogue(
    generated_lesson: dict[str, Any],
    *,
    expected_lesson_id: str,
) -> list[dict[str, str]]:
    try:
        encoded_size = len(json.dumps(generated_lesson, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as error:
        raise SpeakingContextError("Generated lesson must be valid JSON data.") from error
    if encoded_size > MAX_GENERATED_LESSON_JSON_UTF8_BYTES:
        raise SpeakingContextError("Generated lesson is too large.")

    lesson_id = generated_lesson.get("lesson_id")
    if lesson_id != expected_lesson_id:
        raise SpeakingContextError("Generated lesson ID does not match the requested lesson.")

    dialogue = generated_lesson.get("dialogue")
    if not isinstance(dialogue, list) or len(dialogue) != EXPECTED_DIALOGUE_LINE_COUNT:
        raise SpeakingContextError(
            f"Generated dialogue must contain exactly {EXPECTED_DIALOGUE_LINE_COUNT} lines."
        )

    projected: list[dict[str, str]] = []
    total_bytes = 0
    for index, line in enumerate(dialogue):
        if not isinstance(line, dict):
            raise SpeakingContextError(f"Generated dialogue line {index + 1} is invalid.")
        speaker = line.get("speaker")
        if speaker not in {"Anna", "Erik"}:
            raise SpeakingContextError(f"Generated dialogue line {index + 1} has an invalid speaker.")
        raw_text = line.get("text")
        if not isinstance(raw_text, str):
            raise SpeakingContextError(f"Generated dialogue line {index + 1} has invalid text.")
        text = raw_text.strip()
        if not text:
            raise SpeakingContextError(f"Generated dialogue line {index + 1} is empty.")
        if len(text) > MAX_DIALOGUE_LINE_CHARACTERS:
            raise SpeakingContextError(f"Generated dialogue line {index + 1} is too long.")
        if any(character in text for character in ("\x00", "\r", "\n")):
            raise SpeakingContextError(f"Generated dialogue line {index + 1} must be a single text line.")
        total_bytes += len(text.encode("utf-8"))
        if total_bytes > MAX_DIALOGUE_TOTAL_UTF8_BYTES:
            raise SpeakingContextError("Generated dialogue is too large.")
        projected.append({"speaker": str(speaker), "text": text})
    return projected


def build_speaker_instructions(
    lesson: CatalogLesson,
    generated_lesson: dict[str, Any],
    *,
    prompt_path: Path = SPEAKER_PROMPT_PATH,
) -> str:
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise SpeakingContextError("Speaker prompt is empty.")
    lesson_context = project_speaking_lesson_context(lesson)
    dialogue = project_reference_dialogue(generated_lesson, expected_lesson_id=lesson.lesson_id)
    lesson_json = json.dumps(lesson_context, ensure_ascii=False, separators=(",", ":"))
    dialogue_json = json.dumps(dialogue, ensure_ascii=False, separators=(",", ":"))
    return (
        f"{prompt}\n\n"
        f"=== LESSON_CONTEXT ===\n{lesson_json}\n\n"
        f"=== REFERENCE_DIALOGUE ===\n{dialogue_json}"
    )


@dataclass
class SpeakerConversation:
    """Server-owned turn state; the backend, not the model or client, decides when practice ends."""

    instructions: str
    transcription_context: str = ""
    messages: list[dict[str, str]] = field(default_factory=list)
    counted_replies: int = 0
    correction_pending: bool = False
    completed: bool = False
    turn_in_progress: bool = False

    @property
    def is_opening(self) -> bool:
        return not self.messages

    def state(self) -> dict[str, Any]:
        return {
            "counted_replies": self.counted_replies,
            "closing_if_accepted": self.closing_if_accepted(),
        }

    def closing_if_accepted(self) -> bool:
        if self.is_opening:
            return False
        if self.counted_replies >= SPEAKER_TARGET_REPLIES:
            return True
        return self.counted_replies == SPEAKER_TARGET_REPLIES - 1 and not self.correction_pending

    def apply_turn(self, *, transcript: str | None, learner_turn: str, correcting: bool, say: str) -> None:
        closing_allowed = self.closing_if_accepted()
        if transcript is not None:
            self.messages.append({"role": "user", "content": transcript})
        self.messages.append({"role": "assistant", "content": say})
        if transcript is None:
            return
        if learner_turn == "substantive":
            self.counted_replies += 1
        self.correction_pending = correcting
        self.completed = (
            closing_allowed
            and not correcting
            and learner_turn in {"substantive", "correction_repeat"}
        )


@dataclass(frozen=True)
class SpeakingLease:
    user_id: int
    lesson_id: str
    session_id: str
    started_at_monotonic: float
    expires_at_monotonic: float


class SpeakingSessionLimitError(Exception):
    def __init__(self, message: str, *, status_code: int, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_seconds = max(retry_after_seconds, 1)


class SpeakingTurnError(Exception):
    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class SpeakingSessionRegistry:
    """Process-local lease/rate guard holding each active Speaker conversation until it ends or expires."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._active: dict[int, SpeakingLease] = {}
        self._leases: dict[str, SpeakingLease] = {}
        self._conversations: dict[str, SpeakerConversation] = {}
        self._starts: dict[int, deque[float]] = {}

    def begin(
        self,
        user_id: int,
        *,
        lesson_id: str,
        instructions: str,
        transcription_context: str,
        timeout_seconds: int,
        cooldown_seconds: int,
        window_seconds: int,
        max_starts_per_window: int,
    ) -> SpeakingLease:
        now = self._clock()
        with self._lock:
            self._expire_locked(now)
            active = self._active.get(user_id)
            if active is not None:
                raise SpeakingSessionLimitError(
                    "A Speaking practice is already active.",
                    status_code=409,
                    retry_after_seconds=int(active.expires_at_monotonic - now) + 1,
                )

            starts = self._starts.setdefault(user_id, deque())
            cutoff = now - window_seconds
            while starts and starts[0] <= cutoff:
                starts.popleft()
            if starts and now - starts[-1] < cooldown_seconds:
                raise SpeakingSessionLimitError(
                    "Please wait briefly before starting another Speaking practice.",
                    status_code=429,
                    retry_after_seconds=int(cooldown_seconds - (now - starts[-1])) + 1,
                )
            if len(starts) >= max_starts_per_window:
                retry_after = int(starts[0] + window_seconds - now) + 1
                raise SpeakingSessionLimitError(
                    "Speaking practice start limit reached. Try again later.",
                    status_code=429,
                    retry_after_seconds=retry_after,
                )

            starts.append(now)
            lease = SpeakingLease(
                user_id=user_id,
                lesson_id=lesson_id,
                session_id=str(uuid.uuid4()),
                started_at_monotonic=now,
                expires_at_monotonic=now + timeout_seconds,
            )
            self._active[user_id] = lease
            self._leases[lease.session_id] = lease
            self._conversations[lease.session_id] = SpeakerConversation(
                instructions=instructions,
                transcription_context=transcription_context,
            )
            return lease

    def claim_turn(self, user_id: int, lesson_id: str, session_id: str) -> SpeakerConversation:
        with self._lock:
            self._expire_locked(self._clock())
            lease = self._leases.get(session_id)
            if lease is None or lease.user_id != user_id or lease.lesson_id != lesson_id:
                raise SpeakingTurnError("This Speaking practice has ended.", status_code=404)
            conversation = self._conversations[session_id]
            if conversation.completed:
                raise SpeakingTurnError("This Speaking practice is complete.", status_code=409)
            if conversation.turn_in_progress:
                raise SpeakingTurnError("A Speaking turn is already in progress.", status_code=409)
            conversation.turn_in_progress = True
            return conversation

    def release_turn(self, session_id: str) -> None:
        with self._lock:
            conversation = self._conversations.get(session_id)
            if conversation is not None:
                conversation.turn_in_progress = False

    def get(self, user_id: int, lesson_id: str, session_id: str) -> SpeakingLease | None:
        with self._lock:
            self._expire_locked(self._clock())
            lease = self._leases.get(session_id)
            if lease is None or lease.user_id != user_id or lease.lesson_id != lesson_id:
                return None
            return lease

    def finish(self, user_id: int, lesson_id: str, session_id: str) -> SpeakingLease | None:
        with self._lock:
            lease = self._leases.get(session_id)
            if lease is None or lease.user_id != user_id or lease.lesson_id != lesson_id:
                return None
            self._remove_locked(lease)
            return lease

    def abort(self, user_id: int, lesson_id: str, session_id: str) -> SpeakingLease | None:
        """Release a failed start without charging it against start limits."""
        with self._lock:
            lease = self._leases.get(session_id)
            if lease is None or lease.user_id != user_id or lease.lesson_id != lesson_id:
                return None
            self._remove_locked(lease)
            starts = self._starts.get(user_id)
            if starts is not None:
                try:
                    starts.remove(lease.started_at_monotonic)
                except ValueError:
                    pass
                if not starts:
                    self._starts.pop(user_id, None)
            return lease

    def _expire_locked(self, now: float) -> None:
        for lease in [lease for lease in self._leases.values() if lease.expires_at_monotonic <= now]:
            self._remove_locked(lease)

    def _remove_locked(self, lease: SpeakingLease) -> None:
        self._leases.pop(lease.session_id, None)
        self._conversations.pop(lease.session_id, None)
        active = self._active.get(lease.user_id)
        if active is not None and active.session_id == lease.session_id:
            self._active.pop(lease.user_id, None)
