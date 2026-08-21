from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import REPO_ROOT, Settings
from .learning_catalog import CatalogLesson


SPEAKING_PROMPT_PATH = REPO_ROOT / "Materials" / "Speaking_prompt.md"
EXPECTED_DIALOGUE_LINE_COUNT = 20
MAX_DIALOGUE_LINE_CHARACTERS = 800
MAX_DIALOGUE_TOTAL_UTF8_BYTES = 12_000
MAX_GENERATED_LESSON_JSON_UTF8_BYTES = 64_000


class SpeakingContextError(ValueError):
    pass


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


def build_speaking_instructions(
    lesson: CatalogLesson,
    generated_lesson: dict[str, Any],
    *,
    prompt_path: Path = SPEAKING_PROMPT_PATH,
) -> str:
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise SpeakingContextError("Speaking prompt is empty.")
    dialogue = project_reference_dialogue(generated_lesson, expected_lesson_id=lesson.lesson_id)
    lesson_json = json.dumps(lesson.payload, ensure_ascii=False, separators=(",", ":"))
    dialogue_json = json.dumps(dialogue, ensure_ascii=False, separators=(",", ":"))
    return (
        f"{prompt}\n\n"
        f"=== LESSON_CONTEXT ===\n{lesson_json}\n\n"
        f"=== REFERENCE_DIALOGUE ===\n{dialogue_json}\n\n"
        "=== ROLE_GUIDANCE ===\n"
        "The learner is themselves in the lesson situation. Choose the active real-world counterpart "
        "role that makes a guided answer-only interaction natural. The AI always initiates and owns progression."
    )


def build_realtime_session_config(
    settings: Settings,
    *,
    instructions: str,
) -> dict[str, Any]:
    max_output_tokens = settings.speaking_realtime_max_output_tokens
    if not 1 <= max_output_tokens <= 4_096:
        raise ValueError("Speaking Realtime max output tokens must be between 1 and 4096.")
    return {
        "type": "realtime",
        "model": settings.speaking_realtime_model,
        "instructions": instructions,
        "output_modalities": ["audio"],
        "max_output_tokens": max_output_tokens,
        "audio": {
            "input": {
                "noise_reduction": {"type": "near_field"},
                "turn_detection": {
                    "type": "semantic_vad",
                    "eagerness": "low",
                    "create_response": True,
                    "interrupt_response": True,
                },
            },
            "output": {"voice": settings.speaking_realtime_voice},
        },
    }


@dataclass(frozen=True)
class SpeakingLease:
    session_id: str
    expires_at_monotonic: float


class SpeakingSessionLimitError(Exception):
    def __init__(self, message: str, *, status_code: int, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_seconds = max(retry_after_seconds, 1)


class SpeakingSessionRegistry:
    """Process-local V1 lease/rate guard; leases self-expire after the hard session cap."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._active: dict[int, SpeakingLease] = {}
        self._starts: dict[int, deque[float]] = {}

    def begin(
        self,
        user_id: int,
        *,
        timeout_seconds: int,
        cooldown_seconds: int,
        window_seconds: int,
        max_starts_per_window: int,
    ) -> SpeakingLease:
        now = self._clock()
        with self._lock:
            active = self._active.get(user_id)
            if active is not None and active.expires_at_monotonic > now:
                raise SpeakingSessionLimitError(
                    "A Speaking practice is already active.",
                    status_code=409,
                    retry_after_seconds=int(active.expires_at_monotonic - now) + 1,
                )
            self._active.pop(user_id, None)

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
                session_id=str(uuid.uuid4()),
                expires_at_monotonic=now + timeout_seconds,
            )
            self._active[user_id] = lease
            return lease

    def finish(self, user_id: int, session_id: str) -> None:
        with self._lock:
            active = self._active.get(user_id)
            if active is not None and active.session_id == session_id:
                self._active.pop(user_id, None)
