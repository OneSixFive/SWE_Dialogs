# SWE_Dialogs — Speaking Practice V1 Implementation Brief

## Purpose

Add a first-version **Speaking Practice** experience to an individual lesson in SWE_Dialogs.

The goal is not to build a complete speaking-learning subsystem yet. V1 should be a **high-quality, lesson-bound guided roleplay** that lets the learner speak Swedish aloud with a realtime voice model in a way that is:

- tightly connected to the current lesson;
- natural rather than scripted;
- fully guided by the AI;
- useful for practicing spontaneous spoken production;
- able to give selective, brief corrections during the roleplay without destroying conversational flow.

The core product principle is:

> **Follow the learner locally; follow the lesson globally.**

The AI should react naturally to what the learner actually says, while keeping the overall conversation aligned with the lesson’s communicative purpose, difficulty, grammar, vocabulary, and scenario.

---

## V1 Scope

Speaking Practice V1 should:

- live **inside the existing Lesson experience only**;
- be launched from the lesson menu where actions such as lesson regeneration already live;
- use the current lesson as its source of pedagogical context;
- conduct a realtime spoken Swedish roleplay;
- make the AI fully responsible for moving the roleplay forward;
- make the learner primarily responsible for **answering**, not driving the conversation;
- selectively correct important learner errors inline;
- ask the learner to repeat a corrected form once before continuing;
- remain hands-free and use automatic turn detection, with deliberately patient handling of learner pauses and hesitation;
- hide the original dialogue/script while Speaking Practice is active.

V1 should **not**:

- add a separate Speaking tab;
- add speaking history;
- add learner-model / evaluator integration;
- update mastery or learning-target evidence;
- provide scores;
- perform systematic pronunciation assessment;
- require the learner to initiate or manage the conversation;
- require the learner to reproduce the original Anna/Erik dialogue;
- prescribe a fixed 20-turn replay of the generated dialogue.

---

# 1. Entry Point and UX

## Launch

Add a **Speaking Practice** action to the current lesson menu.

The action is lesson-specific. The learner is practicing **this lesson**, not entering a generic Swedish conversation.

The lesson must therefore already provide all context needed to construct the speaking experience.

## During practice

The screen should prioritize the spoken interaction.

Do **not** show:

- the original Anna/Erik dialogue;
- suggested learner responses;
- a transcript that allows the learner to read ahead;
- answer options.

This should be **pure speaking**, not reading-assisted speaking.

It is fine to show a very small amount of orienting context before or during the session, for example:

- the situation;
- the learner’s role;
- the broad communicative goal.

Example:

> **Situation:** You meet a new colleague by the coffee machine.  
> **Goal:** Introduce yourself and talk briefly about where you live and work.

This should not become a script or cheat sheet.

---

# 2. Relationship to the Lesson

Speaking Practice must be strongly grounded in the current lesson.

The voice model should receive enough lesson context to understand:

- course level / intended learner difficulty;
- one-sentence lesson goal;
- real-life context;
- communicative function;
- dialogue scenario;
- grammar target;
- allowed/supporting grammar;
- vocabulary theme;
- active vocabulary;
- useful chunks;
- dialogue shape / intended conversational progression;
- the generated Anna/Erik dialogue.

The lesson payload is the **pedagogical source of truth**.

The generated Anna/Erik dialogue is a **reference example of a successful realization of that lesson**.

It is not a script to replay.

---

# 3. Reference Dialogue: How It Should Be Used

The existing generated dialogue should help the realtime model understand:

- what kind of real-world interaction the lesson represents;
- the approximate conversational progression;
- the expected level and complexity;
- the kinds of vocabulary and grammar that should naturally arise;
- what a successful conversation for this lesson roughly looks like.

However:

> **The Speaking Practice must not attempt to reproduce the original dialogue line-by-line.**

The learner replaces one side of the interaction, but the model should not expect the learner to say Anna’s or Erik’s original lines.

The model should react to the learner’s real answers.

Example:

If the original dialogue contains:

> Erik: Var bor du?  
> Anna: Jag bor i Lund.

and the learner says:

> Jag bor precis vid Triangeln i Malmö.

the model should respond naturally to that answer, for example:

> Jaså, mitt i stan alltså! Hur länge har du bott där?

It should **not** try to force the conversation back toward Lund or toward the exact next line of the original dialogue.

The desired rule is:

> **Follow the learner locally; follow the lesson globally.**

Local adaptation can be flexible.

Global alignment should remain strong.

The model should preserve:

- scenario;
- communicative goal;
- lesson difficulty;
- target language;
- broad subject matter;
- overall purpose of the exercise.

---

# 4. Guided Roleplay: AI Owns Progression

This is a deliberate V1 constraint.

The learner’s task is primarily to **answer**.

The AI’s task is to **drive the entire roleplay forward**.

The model must never wait for the learner to decide what happens next.

It must never implicitly require the learner to:

- ask the next question;
- introduce the next topic;
- decide when to move on;
- initiate a new conversational beat.

After every successfully completed learner answer, there are only two main possibilities:

1. the answer is good enough -> AI advances the roleplay;
2. the answer contains an important error -> AI runs the correction loop, then advances the roleplay.

This should remove ambiguity about conversational ownership.

## Important wording principle

Do not instruct the model simply to:

> always ask a question.

That would become mechanical.

Instead:

> **Every AI roleplay turn should naturally create a clear opportunity for the learner to respond.**

A response opportunity can be:

- a direct question;
- a request to explain;
- a reaction followed by a prompt;
- an invitation to describe something;
- a natural conversational cue.

Example:

> Jaså, du jobbar på IKEA. Berätta lite om vad du gör där.

is preferable to forcing every turn into a literal question.

---

# 5. If the Learner Asks a Question Anyway

The learner is not prohibited from asking questions.

Example:

> AI: Var bor du någonstans?  
> Learner: Jag bor i Malmö. Och du?

The AI should answer naturally, briefly, and then immediately reassert control of progression:

> Jag bor i Lund faktiskt. Hur länge har du bott i Malmö?

The rule is:

> **The learner may ask questions, but the learner is never responsible for keeping the conversation moving.**

---

# 6. Core Interaction Loop

The normal interaction state is **ROLEPLAY**.

A typical successful loop is:

1. AI speaks in character and creates a response opportunity.
2. Learner answers.
3. AI evaluates whether the learner’s answer needs interruption-level correction.
4. If no correction is needed:
   - AI remains in character;
   - reacts naturally;
   - advances the scenario.
5. If correction is needed:
   - AI briefly leaves the role;
   - gives one concise correction;
   - asks the learner to repeat the corrected form;
   - waits for the repetition;
   - accepts a sufficiently good repetition;
   - returns immediately to the role;
   - advances the scenario.

Conceptually:

```text
ROLE
  ->
learner answer
  ->
[good enough] -----------------> ROLE advances

or

ROLE
  ->
learner answer
  ->
CORRECTION
  ->
learner repeats
  ->
ROLE resumes and advances
```

There should be no ambiguous state after a successful learner answer or corrected repetition.

The AI advances.

---

# 7. Inline Correction Behavior

Inline correction is a **core V1 feature**, not a future evaluator feature.

The purpose is to reproduce one of the main benefits of speaking with a real language teacher:

- teacher plays the role;
- student answers;
- teacher briefly exits the role to correct an important error;
- student repeats correctly;
- teacher returns to the role and continues naturally.

Example:

> **Erik:** Jaha, hur länge har du bott i Malmö?  
> **Learner:** Jag bor i Malmö sedan fem år.  
> **Teacher:** Almost. Say: “Jag har bott i Malmö i fem år.” Try that.  
> **Learner:** Jag har bott i Malmö i fem år.  
> **Erik:** Fem år, okej! Trivs du bra här?

The role/teacher/role transition should feel deliberate and clean.

---

# 8. Correction Threshold

The model must **not correct every imperfection**.

Constant correction would destroy fluency and turn the interaction into a grammar drill.

The model should interrupt primarily for:

### High priority

- errors involving the lesson’s main grammar target;
- errors involving important target vocabulary or useful chunks;
- errors that materially change the learner’s intended meaning;
- errors that make the utterance clearly unnatural or difficult to understand;
- repeated errors that are highly relevant to the current lesson.

### Low priority / usually ignore

- minor imperfections unrelated to the lesson;
- harmless stylistic differences;
- slightly non-native wording when meaning is clear;
- small article/preposition/etc. mistakes when they are not important to the lesson;
- alternative phrasing that is natural Swedish even if different from the lesson dialogue.

The model should prefer:

> **lesson-relevant correction over exhaustive correction.**

Lesson context should therefore affect not only **what the conversation is about**, but also **what the tutor cares enough to interrupt for**.

---

# 9. Correction Style

Corrections must be:

- short;
- clear;
- focused on one issue;
- immediately actionable;
- suitable for oral repetition.

Avoid:

- long grammar explanations;
- multiple corrections at once;
- meta-analysis;
- lists of rules;
- explanations that derail the scenario.

A correction should normally provide the correct form directly.

Example:

> Nästan. Säg: “Jag har bott här i fem år.” Försök igen.

or, if English is used for tutor-mode clarity:

> Almost. Say: “Jag har bott här i fem år.” Try that.

The exact tutor-language choice can be decided during implementation/testing, but the correction itself must remain compact.

---

# 10. Required Repetition

When the model chooses to interrupt for correction:

- it should ask the learner to repeat the corrected form;
- it should wait for that repetition before continuing;
- it should not advance the roleplay immediately after giving the correction.

After the learner repeats:

- accept a sufficiently correct version;
- do not demand robotic exact reproduction if the learner expresses the corrected idea naturally;
- do not enter an endless correction loop over minor remaining imperfections;
- resume the roleplay immediately.

The corrected repetition is part of the learning interaction, not an evaluator record.

---

# 11. Roleplay Naturalness

The roleplay should sound like a real interaction appropriate to the lesson.

The model should:

- stay in character during normal conversation;
- react to the learner’s actual content;
- use short enough turns that the learner speaks frequently;
- avoid monologues;
- avoid sounding like a quiz machine;
- avoid merely marching through lesson vocabulary;
- use target vocabulary and grammar naturally rather than forcing them into every turn;
- keep Swedish suitable for the learner’s level;
- make the interaction feel conversational even though the AI owns progression.

The model may adapt the conversation to what the learner says as long as it remains globally aligned with the lesson.

---

# 12. Teacher Mode vs Role Mode

The model needs a clear behavioral distinction between two modes.

## ROLE mode

Default state.

The model:

- plays the assigned character;
- speaks naturally in the lesson scenario;
- reacts to learner content;
- advances the conversation;
- does not explain language.

## TEACHER mode

Used only when a significant correction is warranted or the learner explicitly asks a language question.

The model:

- briefly stops pretending to be the character;
- gives the minimal useful correction/help;
- asks for repetition when correcting;
- returns to ROLE mode immediately afterward.

Teacher mode should be **brief and exceptional**.

Role mode should dominate the session.

---

# 13. Learner Questions About Language

If the learner explicitly asks for help or clarification, the model may temporarily leave the role.

Examples:

- “How do I say X?”
- “What does that mean?”
- “Can you repeat?”
- “Can you speak more slowly?”
- “Why is it *har bott*?”

The model should answer briefly at an appropriate level, then return to the roleplay and continue driving the interaction.

It should not turn one question into a long lesson unless absolutely necessary.

---

# 14. Handling Hesitation and Turn Completion

V1 should use **automatic turn detection** and aim for a natural hands-free interaction.

However, language learners pause more than fluent speakers.

The experience must therefore be deliberately patient.

The system/model should expect:

- hesitation;
- filler sounds;
- searching for vocabulary;
- self-correction;
- slow sentence construction;
- pauses inside an unfinished answer.

Example:

> Jag… eh… jag kommer från…

should not automatically be treated as a finished semantic answer merely because there is a pause.

The intended behavior is:

> **Give the learner reasonable space to finish.**

Once the learner has provided a meaningful answer to the current prompt, the AI should not wait for the learner to ask something else.

It should either:

- correct; or
- advance.

Hands-free natural conversation is the desired default.

---

# 15. When the Learner Is Stuck

The model should scaffold rather than immediately give up or move on.

If the learner clearly cannot formulate an answer, the AI can:

1. repeat or simplify the question;
2. slow down;
3. rephrase;
4. provide a small lexical cue;
5. provide a short starter phrase if necessary.

The goal is still to have the learner **produce the answer aloud**.

Avoid providing a complete answer too early.

If a full model answer is eventually necessary, ask the learner to repeat or adapt it.

---

# 16. Difficulty and Language Control

The lesson payload determines the expected language level.

The realtime model should not casually escalate beyond it.

It should:

- use vocabulary appropriate to the lesson/course level;
- keep syntax reasonably aligned with the lesson;
- use allowed supporting grammar naturally;
- avoid introducing lots of unrelated advanced structures;
- prefer natural spoken Swedish;
- remain understandable without becoming artificially simplistic.

The speaking exercise is an extension of the lesson, not an independent free-chat session.

---

# 17. Conversation Length and Ending

The original 20-line dialogue gives a useful sense of scope, but Speaking Practice does **not** reproduce it line-by-line. The model instead owns a semantic count of exactly **10 substantive learner replies**; a repetition requested inside a correction loop does not count.

The model should end when the lesson’s communicative goal has been meaningfully exercised and the roleplay has reached a natural conclusion.

It should not:

- prolong the conversation indefinitely;
- invent unrelated topics just to keep talking;
- insist on covering every exact original dialogue beat.

The ending should feel like the end of the real-world interaction.

Example:

> Trevligt att träffas! Vi ses säkert senare.

No evaluator or score is required afterward in V1.

A simple completion state is sufficient.

---

# 18. Pronunciation

Systematic pronunciation assessment is **out of scope for V1**.

The model should not:

- produce pronunciation scores;
- claim phoneme-level accuracy;
- systematically interrupt on accent/pronunciation;
- present itself as a reliable pronunciation evaluator.

The initial focus is:

- grammar;
- vocabulary;
- phrasing;
- comprehensibility;
- meaningful spoken production.

If a pronunciation issue is so severe that the model genuinely cannot understand the learner, it may ask them to repeat naturally, but this should not become pronunciation tutoring.

---

# 19. Prompt Design Priorities

Most of the quality of this feature will depend on the realtime session instructions.

The prompt should make the following hierarchy extremely clear:

## Highest-level objective

Conduct a natural Swedish roleplay that gives the learner purposeful spoken practice of the current lesson.

## Behavioral invariants

1. **You own progression.**
2. **The learner primarily answers.**
3. **Never wait for the learner to drive the next conversational beat.**
4. **Every roleplay turn creates a clear response opportunity.**
5. **Follow the learner locally; follow the lesson globally.**
6. **The generated dialogue is a reference, not a script.**
7. **Correct selectively, not exhaustively.**
8. **Prioritize lesson-relevant errors.**
9. **When correcting: briefly leave role -> give one correction -> ask for repetition -> resume role.**
10. **Normal conversation should dominate over teaching commentary.**
11. **Be patient with learner hesitation.**
12. **Do not assess pronunciation systematically.**

The prompt should strongly distinguish:

- pedagogical context;
- reference dialogue;
- roleplay behavior;
- correction behavior;
- turn/progression rules.

Avoid duplicating the same behavioral instructions in many sections if one precise rule can govern them.

---

# 20. Conceptual Prompt Shape

This is not intended as final prompt copy, but the realtime instructions should conceptually contain something like:

```text
PEDAGOGICAL SOURCE OF TRUTH
<current lesson payload>

REFERENCE CONVERSATION
<generated Anna/Erik dialogue>

YOUR ROLE
<assigned role / character>

LEARNER ROLE
<learner replaces the other participant>

GOAL
Recreate the communicative situation of this lesson as a natural spoken
roleplay.

The reference conversation shows one successful version of the lesson.
It is not a script.

Follow the learner locally; follow the lesson globally.

You always control conversational progression.
The learner primarily responds to you.
Never wait for the learner to ask the next question or introduce the next
topic.

Every roleplay turn should naturally create a clear response opportunity.

React naturally to what the learner actually says.
Do not require the learner to reproduce the reference dialogue.

CORRECTION
After each learner answer, decide whether there is a significant,
high-confidence error worth interrupting for.

Prefer correction of:
- the current lesson's grammar target;
- important target vocabulary/chunks;
- errors that materially affect meaning or naturalness.

Ignore minor unrelated imperfections.

If correction is needed:
1. briefly leave the role;
2. give one concise correction;
3. ask the learner to repeat it;
4. wait for the repetition;
5. accept a sufficiently good repetition;
6. return immediately to the role;
7. continue the scenario.

Do not give long grammar explanations.
Do not correct every mistake.

TURN BEHAVIOR
Learners may hesitate, pause, search for words, or self-correct.
Give them reasonable space to finish.

Once they have provided a meaningful answer, do not wait for them to drive
the conversation. Correct if needed, otherwise advance.
```

Codex should refine this into the actual production prompt and session behavior.

---

# 21. Examples of Desired Behavior

## A. Normal answer: continue naturally

> **AI / Erik:** Hej! Jag tror inte vi har träffats förut. Vad heter du?  
> **Learner:** Jag heter Dima.  
> **AI / Erik:** Trevligt, Dima! Var kommer du ifrån?

No unnecessary praise or analysis.

---

## B. Lesson-relevant error: correct, repeat, resume

> **AI / Erik:** Hur länge har du bott i Malmö?  
> **Learner:** Jag bor i Malmö sedan fem år.  
> **AI / Teacher:** Nästan. Säg: “Jag har bott i Malmö i fem år.” Försök igen.  
> **Learner:** Jag har bott i Malmö i fem år.  
> **AI / Erik:** Fem år! Då känner du säkert stan ganska bra. Vad tycker du bäst om med Malmö?

---

## C. Minor imperfection: do not derail

> **Learner:** Jag jobbar där ungefär tre år.

If the lesson is not about duration expressions and the meaning is clear, the model may simply continue rather than turning every utterance into a correction exercise.

---

## D. Learner asks something

> **AI / Erik:** Var bor du någonstans?  
> **Learner:** Jag bor i Malmö. Och du?  
> **AI / Erik:** Jag bor i Lund faktiskt. Hur länge har du bott i Malmö?

The learner's question is answered naturally, but the AI still owns progression.

---

## E. Learner hesitates

> **Learner:** Jag… eh… jag jobbar… på…

Do not jump in immediately.

Give the learner reasonable time to complete the answer.

---

## F. Learner is stuck

> **AI:** Vad gör du på jobbet?  
> **Learner:** Eh… jag vet inte hur man säger…  
> **AI / Teacher:** Du kan börja med “Jag jobbar med…”.  
> **Learner:** Jag jobbar med försäljning.  
> **AI / Role:** Jaså! Hur länge har du jobbat med det?

Scaffold briefly, then return to conversation.

---

# 22. Acceptance Criteria

V1 should be considered successful if the following are true.

## Lesson grounding

- The roleplay clearly feels like an extension of the current lesson.
- It stays aligned with the lesson scenario and communicative goal.
- Target grammar/vocabulary appear naturally where appropriate.
- The AI does not behave like a generic Swedish chat bot.

## Naturalness

- The AI reacts to the learner’s real content.
- It does not reproduce the Anna/Erik dialogue mechanically.
- Unexpected but valid learner answers lead to natural local adaptation.
- The interaction remains globally aligned with the lesson.

## Conversation ownership

- The AI consistently moves the conversation forward.
- The learner is never required to decide what happens next.
- The AI does not wait for the learner to ask the next question.
- Every AI roleplay turn gives the learner a clear reason to respond.

## Correction

- Important lesson-relevant errors are corrected.
- Minor unrelated errors are often allowed to pass.
- Corrections are short.
- Only one main issue is corrected at a time.
- The learner is asked to repeat the corrected form.
- The AI returns to role immediately after successful repetition.
- Corrections do not dominate the conversation.

## Turn-taking

- The interaction is hands-free.
- The system tolerates realistic learner hesitation.
- The AI does not frequently interrupt unfinished answers.
- Once an answer is semantically complete, the AI proceeds without waiting for learner initiative.

## Scope discipline

- No evaluator integration.
- No speaking score.
- No speaking history.
- No separate Speaking tab.
- No systematic pronunciation evaluation.
- No visible reference script during practice.

---

# 23. V1 Product Definition in One Paragraph

**Speaking Practice V1 is a lesson-bound, hands-free Swedish guided roleplay launched from the existing Lesson menu. The realtime model receives the lesson context and generated dialogue, but treats the dialogue only as a reference example. The AI owns all conversational progression and continuously creates clear opportunities for the learner to answer aloud. It reacts naturally to the learner’s actual responses — following the learner locally while following the lesson globally. When the learner makes an important, high-confidence, lesson-relevant error, the AI briefly exits the role, gives one concise correction, asks the learner to repeat the corrected form, then immediately resumes the roleplay and moves the conversation forward. Minor errors are ignored when correction would hurt fluency. The original dialogue is not shown during practice, automatic turn detection is deliberately patient with learner hesitation, and V1 includes no evaluator integration, scoring, history, pronunciation assessment, or separate Speaking module.**
