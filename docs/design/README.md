# Retro Design

Approved direction (October 2026): 1980s Swedish office electronics (Ericofon handset, Facit/Odhner calculators, Ericsson portables) in a walnut, mustard, burnt-orange, olive, manila and amber-CRT palette. The mockups in this folder are the reference:

- `01-lessons-lesson-speaking.jpg`: lesson path, lesson screen, Speaking. Desk props (plants, pencils, cabinets) are not part of the app.
- `02-signin-vocabulary.jpg`: Sign in, `Ord` history slips, vocabulary quiz.
- `03-dialog-menu-more.jpg`: dialogue transcript, lesson `⋯` menu, `Mer`.
- `04-clean-learning-text.jpg`: the binding rule for learning text (supersedes the chat parts of 01 and 02).
- `05-middle-ground-target.png`: the previous build target. Calmer than 01–03: real wood, matte keycaps, one realistic object per screen, plain paper.
- `06-device-*.png`: the "learning device" direction: each screen is the faceplate of one module of the same instrument. `06-device-graphite.png` is the approved colourway (graphite metal, smoked walnut ledge, bone and graphite keys, one muted rust accent, dim amber readouts); sage and cream were the alternatives.
- `07-path-variants.png`, `07-lesson-variants.png`: the current build target. The lesson path is variant 1 (step sequencer, one row of seven keys per week, lamps for finished days). The lesson screen is variant B (slim key strip, one tape-head strip, paper fed out under a roller), without the header it shows. No walnut rim around the screen: the phone's own bezel is the cabinet.

Rules:

- Learning text (tutor, learner, dialogue, sentences to translate) sits on one plain paper surface. No bubbles, chips, plaques, or stamps inside it. Tutor lines are left-aligned dark-brown ink under `LÄRAREN`; learner lines are right-aligned orange ink under `DU`. A red-pencil underline for corrections is the only extra.
- Metal, wood, keycaps, counters and amber readouts are for chrome only. The rust accent marks the one thing to press (current lesson, play, active tab, talk) and nothing else.
- Learners do not see curriculum metadata: no stage text, lesson goals, grammar focus, or scenario. Lessons and weeks are numbered per level (B2 restarts at 1); each sequencer row carries a small level tag (B1/B2) and its week number.
- Interface labels are uppercase Swedish.
- Fonts are tokens in `RetroFont`. Current placeholders: American Typewriter (labels, wordmark), system monospaced (reading text, digits). Candidates for licensing: Tratex or Bosis (labels) and Berling Nova (reading text).

Artwork:

- Materials and fixed objects are images in `Assets.xcassets/Retro` (graphite faceplate tile, wood tile, cassette body and reel hub, VU meter face, brass plate, Ericofon front view recoloured to ivory, school computer). Anything that changes state or holds text is code: keys, needle, reels, LED strip, readouts, screen text, labels.
- Images were generated in ChatGPT on a flat magenta background, then keyed out; the wood and faceplate tiles were made seamless with an offset blend. Code that overlays an image (label, hubs, needle pivot, CRT text) uses pixel coordinates measured from that image, so re-measure them if an image is replaced.
- Light comes from the top-left everywhere.
