from __future__ import annotations

import hashlib
from typing import Any

DEFAULT_TTS_MODEL = "gemini-2.5-pro-preview-tts"
VOICE_CONFIG_VERSION = "anna-aoede_erik-enceladus_v1"
MAX_TTS_TEXT_CHARACTERS = 20_000


class InvalidLessonAudioSource(ValueError):
    pass


def canonical_tts_text(generated_lesson: dict[str, Any]) -> str:
    dialogue = generated_lesson.get("dialogue")
    if not isinstance(dialogue, list) or not dialogue:
        raise InvalidLessonAudioSource("Generated lesson has no dialogue.")

    lines: list[str] = []
    for item in dialogue:
        if not isinstance(item, dict):
            raise InvalidLessonAudioSource("Generated lesson dialogue is invalid.")
        speaker = item.get("speaker")
        text = item.get("text")
        if speaker not in {"Anna", "Erik"} or not isinstance(text, str) or not text.strip():
            raise InvalidLessonAudioSource("Generated lesson dialogue is invalid.")
        lines.append(f"{speaker}: {text.strip()}")

    result = "\n".join(lines)
    if len(result) > MAX_TTS_TEXT_CHARACTERS:
        raise InvalidLessonAudioSource("Generated lesson dialogue is too long.")
    return result


def lesson_audio_content_hash(
    generated_lesson: dict[str, Any],
    *,
    model: str = DEFAULT_TTS_MODEL,
    voice_config_version: str = VOICE_CONFIG_VERSION,
) -> str:
    source = f"{canonical_tts_text(generated_lesson)}\n{model}\n{voice_config_version}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()
