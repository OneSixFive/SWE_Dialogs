# Vocabulary Materials

This directory contains vocabulary extracted from the per-lesson curriculum briefs in `Materials/Lessons/`.
The lesson briefs remain the source of truth; regenerate these files with:

```bash
scripts/build-vocabulary-materials.py
```

Each curriculum level has one vocabulary file. Its `stages` array groups vocabulary by stage, and each stage's `lessons` array keeps vocabulary grouped by lesson. Lesson identifiers and course positions support filtering at or before the learner's current progression while allowing vocabulary practice to load the level as one source.

Vocabulary is separated as follows:

- `vocabulary.words`: single-word entries from the lesson's `active_words`.
- `vocabulary.expressions.active`: multi-word entries from `active_words`.
- `vocabulary.expressions.useful_chunks`: reusable phrases and sentence frames from `useful_chunks`.

Learner-specific state such as saved items, difficulty scores, and encounter history should be stored separately and refer back to these source entries rather than being written into these curriculum files.
