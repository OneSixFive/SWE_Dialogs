from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .lesson_audio import canonical_tts_text
from .openai_client import generator_schema


LESSON_RECIPE_SCHEMA_VERSION = 1
AUDIO_RECIPE_SCHEMA_VERSION = 1
LESSON_VALIDATOR_CONTRACT_VERSION = "generated_lesson_v2"
TTS_TEXT_NORMALIZATION_VERSION = "anna_erik_dialogue_v1"
LESSON_MAX_OUTPUT_TOKENS = 4_000


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def json_sha256(value: Any) -> str:
    return sha256_text(canonical_json(value))


@dataclass(frozen=True)
class LessonRecipe:
    document: dict[str, Any]
    fingerprint: str


@dataclass(frozen=True)
class AudioRecipe:
    document: dict[str, Any]
    fingerprint: str


def lesson_recipe(
    settings: Settings,
    *,
    lesson_id: str,
    payload: dict[str, Any],
    shared_base_prompt: str,
    generator_prompt: str,
) -> LessonRecipe:
    document = {
        "recipe_schema_version": LESSON_RECIPE_SCHEMA_VERSION,
        "manual_recipe_version": settings.lesson_generator_recipe_version,
        "provider": "openai",
        "requested_model": settings.lesson_generator_model,
        "reasoning_effort": settings.lesson_generator_reasoning_effort,
        "max_output_tokens": LESSON_MAX_OUTPUT_TOKENS,
        "shared_base_prompt_sha256": sha256_text(shared_base_prompt),
        "generator_prompt_sha256": sha256_text(generator_prompt),
        "response_schema_sha256": json_sha256(generator_schema()),
        "validator_contract_version": LESSON_VALIDATOR_CONTRACT_VERSION,
        "curriculum_payload_sha256": json_sha256(payload),
        "lesson_id": lesson_id,
    }
    return LessonRecipe(document=document, fingerprint=json_sha256(document))


def audio_recipe(settings: Settings) -> AudioRecipe:
    document = {
        "recipe_schema_version": AUDIO_RECIPE_SCHEMA_VERSION,
        "manual_recipe_version": settings.lesson_tts_recipe_version,
        "provider": "gemini",
        "requested_model": settings.lesson_tts_model,
        "voice_config_version": settings.lesson_tts_voice_config_version,
        "text_normalization_version": TTS_TEXT_NORMALIZATION_VERSION,
        "output_container": "wav",
        "output_encoding": "pcm_s16le",
        "sample_rate_hz": 24_000,
        "channels": 1,
    }
    return AudioRecipe(document=document, fingerprint=json_sha256(document))


def lesson_content_hash(generated_lesson: dict[str, Any]) -> str:
    projected = {
        "lesson_id": generated_lesson.get("lesson_id"),
        "dialogue": generated_lesson.get("dialogue"),
        "comprehension_questions": generated_lesson.get("comprehension_questions"),
    }
    return json_sha256(projected)


def artifact_audio_identity(settings: Settings, generated_lesson: dict[str, Any]) -> tuple[str, str, AudioRecipe]:
    dialogue_hash = sha256_text(canonical_tts_text(generated_lesson))
    recipe = audio_recipe(settings)
    content_hash = sha256_text(f"{dialogue_hash}:{recipe.fingerprint}")
    return dialogue_hash, content_hash, recipe


def shared_audio_relative_path(content_hash: str) -> Path:
    if len(content_hash) != 64 or any(character not in "0123456789abcdef" for character in content_hash):
        raise ValueError("Invalid audio content hash.")
    return Path(content_hash[:2]) / f"{content_hash}.wav"
