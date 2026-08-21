Verdict: the foundation is sound, but I would not implement the complete V1 unchanged. It is ready for the backend/WebRTC spike; several details should be amended before building the production flow.

The OpenAI architecture is current: `gpt-realtime-2.1` exists, the unified `/v1/realtime/calls` bootstrap is supported, WebRTC is recommended for mobile clients, the safety-identifier header is correct, and `semantic_vad` with low eagerness/interruption is valid. [OpenAI WebRTC guide](https://developers.openai.com/api/docs/guides/realtime-webrtc), [VAD guide](https://developers.openai.com/api/docs/guides/realtime-vad), [model documentation](https://developers.openai.com/api/docs/models/gpt-realtime-2.1).

The items to resolve are:

1. **Role assignment can defeat the lesson target.**\
   The proposed rule “AI plays the first reference speaker” does not ensure that the learner produces the target language. For example, the B1 wh-question lesson has Anna asking the questions; if Anna opens and the AI becomes Anna, the learner mostly answers even though question production is the lesson goal. A keyword scan found 57/224 lessons involving asking, requesting, suggesting, inviting, checking, or negotiating.

   See the [role-assignment rule (line 596)]\(C:/Users/DMSHI5/OneDrive - Inter IKEA Group/Personal/SWE\_Dialogs/docs/next\_step/SWE\_Dialogs\_Speaking\_Practice\_V1\_Architecture\_Plan.md:596) and the [question lesson (line 11)]\(C:/Users/DMSHI5/OneDrive - Inter IKEA Group/Personal/SWE\_Dialogs/Materials/Lessons/B1/Lesson\_brief\_JSONs/B1\_Stage\_1\_Week\_1\_Day\_4.json:11).

   Replace first-speaker assignment with a lesson-aware role description containing:
   - AI counterpart role;
   - learner role;
   - minimal scenario facts where needed;
   - two to four learner production targets/speech acts.
   The AI can still own progression while explicitly eliciting a question, request, clarification, or negotiation from the learner.
2. **The “trusted generated dialogue” is not actually trusted.**\
   `generated_lesson` is currently an arbitrary dictionary uploaded by the client, and backend validation checks essentially only that its `lesson_id` matches. The Speaking proposal then places that content inside the Realtime instructions. That contradicts its acceptance criterion that the client cannot replace lesson context with arbitrary prompt data.

   See [models.py (line 105)]\(C:/Users/DMSHI5/OneDrive - Inter IKEA Group/Personal/SWE\_Dialogs/backend/app/models.py:105) and [main.py (line 1028)]\(C:/Users/DMSHI5/OneDrive - Inter IKEA Group/Personal/SWE\_Dialogs/backend/app/main.py:1028).

   Before prompt construction, validate and project it into a bounded dialogue DTO: valid lesson ID, exactly expected speakers/lines, non-empty bounded text, maximum total size, and no unrelated fields. Ideally strengthen lesson-session upload validation too.
3. **Cost and abuse guardrails are missing.**\
   The new authenticated endpoint has no proposed per-user start limit, concurrency control, hard session duration, or per-response output cap. The plan also deliberately omits per-user Realtime usage reporting. Realtime charges accrue per response and later turns resend the growing conversation, so an uncontrolled or looping session can become expensive. [OpenAI cost guide](https://developers.openai.com/api/docs/guides/realtime-costs).

   Settle and document:
   - maximum session length—10 minutes is a reasonable V1 starting point;
   - per-user session-start rate/cooldown;
   - bounded `max_output_tokens` per response;
   - whether it is acceptable that Speaking appears only in organization-level actual cost and not the per-user dashboard.
   The last item is a product/operations decision. If per-user accounting is required, it expands V1 beyond the current “no migration/telemetry” scope.
4. **The WebRTC dependency is still a spike, not an implementation decision.**\
   The plan explicitly leaves package selection/version verification open. Google documents building `WebRTC.framework`; a maintained community SwiftPM XCFramework such as [`stasel/WebRTC`](https://github.com/stasel/WebRTC) is a reasonable spike candidate, but it still needs exact-version pinning and verification on the simulator and `iPhone_D`.
5. **The sync API must be newly implemented, not merely reused.**\
   The proposal recognizes this, but it is worth making explicit in the implementation contract: current `uploadDirtySessions()` returns no success/failure and its sync worker swallows network errors, leaving the record dirty. Calling it before Speaking would not prove that the current generation reached the server.

   See [LessonSessionStore.swift (line 231)]\(C:/Users/DMSHI5/OneDrive - Inter IKEA Group/Personal/SWE\_Dialogs/SWE\_Dialogs/SWE\_Dialogs/LessonSessionStore.swift:231).

   Add a lesson-specific, throwing `ensureLessonSynced(...)` that confirms the expected generation identity server-side or fails visibly.

The prompt proposal is a good behavioral specification, but I would not freeze it as production copy yet. OpenAI recommends starting with a relatively minimal Realtime prompt and adding rules based on evaluations; the current proposal is about 1,500 words and repeats several absolute instructions. [Realtime prompting guidance](https://developers.openai.com/api/docs/guides/realtime-models-prompting). First fix learner-production/role assignment, then evaluate a fixed set of lesson archetypes—question formation, service request, narration, clarification, negotiation, and opinion.

So: **start Phase 1 and the WebRTC transport spike now, but settle findings 1–4 before treating the three documents as an implementation-complete specification.** No new lesson phase, Speaking database entity, evaluator integration, transcript persistence, or alternate transport is needed.
