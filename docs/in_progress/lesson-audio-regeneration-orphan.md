# Lesson audio regeneration orphan

## Symptom

For user ID `2`, the previous lesson,
`b1_stage_1_week_2_day_4`, appeared unable to generate audio. Retrying audio
and regenerating the lesson did not make the new audio available. The next
lesson, `b1_stage_1_week_2_day_5`, generated successfully.

## Cause

The failure was in the regeneration hand-off, not in Gemini TTS or the audio
worker.

- The original shared artifact (`fdfc655a-8347-48a5-a4f4-7072892a57b7`) was
  generated on 2026-08-26 and its audio job completed successfully, producing
  a 2,389,050-byte WAV with content hash beginning `721d2e627271`.
- Audio retries on 2026-08-27 used that old content hash and returned the
  already-completed shared audio. They did not request audio for regenerated
  content.
- Regeneration created a new private artifact
  (`cefbc1a6-8da0-478f-9cf7-62b47a0cafb2`) at 14:20:29 UTC, but no
  `artifact_audio_jobs` row or audio cache entry was created for it.
- No session update or audio-generation request for day 4 followed publication
  of the private artifact. The durable session therefore remained attached to
  the old shared artifact.
- The next lesson's audio job completed normally, confirming that the provider
  and worker were functioning.

The current flow is client-dependent: the app first resolves and publishes an
artifact, then uploads the session binding, then requests audio. If the app
task is cancelled, the view changes, or connectivity drops between those
steps, the artifact can be left orphaned with no audio job.

## Proposed fix

Make regeneration a session-specific, server-owned durable operation:

1. Add a session regeneration endpoint. The app supplies a client-generated
   operation key, persisted before the request is sent, and the current
   `server_updated_at` concurrency token. Before calling the provider, store a
   leased generation operation with a uniqueness constraint on user, lesson,
   and operation key. Reusing the key returns the completed result, reports an
   active attempt, or reclaims an expired attempt; it never creates another
   private artifact.
2. Keep generation request-driven: the request that successfully claims the
   operation generates the replacement lesson, as today. Do not add a separate
   always-running lesson-generation worker unless independent background
   generation becomes a product requirement. If a request disappears before
   completion, its lease expires and a retry with the same operation key can
   safely run the attempt again.
3. After generation succeeds, finalize the hand-off in one database
   transaction. First verify that the target session still has the expected
   concurrency token; if it does not, record a conflict without replacing newer
   session state. Otherwise:
   - publish the private artifact;
   - attach it to `lesson_sessions`;
   - reset the lesson session state and messages using the server-defined fresh
     state;
   - insert the matching `artifact_audio_jobs` row for the current audio recipe
     and content hash; and
   - record the operation key as completed with the resulting artifact ID.
   No external provider or file operation should run inside this transaction.
4. Return the attached artifact, updated session concurrency token, and audio
   status. The app should adopt that server result, save the artifact locally,
   and poll the existing durable audio job. Regeneration must no longer depend
   on a follow-up
   `uploadDirtySessions()` or separate audio-generation request.
5. Add one focused integration test that expires or interrupts the first
   attempt, retries with the same operation key, and verifies that there is
   exactly one private artifact, that it is attached to the reset session, and
   that exactly one matching audio job exists.

No live data was modified and the backend was not restarted during the
investigation.
