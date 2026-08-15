# AXON 0.1.1 — Voice Recovery + File Viewer Reliability

## Purpose
This is the 0.1-series maintenance release built on AXON 0.1.0 without redesigning the UI.

## Voice fix
AXON no longer treats a transient Gemini Live disconnect as a failed voice command.

Previously:
1. Gemini Live websocket/session disappeared.
2. The voice supervisor temporarily had `running == False`.
3. A verified router/browser action completed successfully.
4. `_deliver_voice_response()` called `send_text()`.
5. `send_text()` returned `False` because the Live engine was down.
6. AXON raised `Gemini Live TTS session is unavailable` and reported the whole voice command as failed.

Now:
1. Verified command results are always placed in the durable in-memory TTS queue.
2. If the Live supervisor has stopped unexpectedly, the voice engine automatically starts a recovery supervisor.
3. The response waits in the queue while Gemini Live reconnects.
4. The next healthy Live session drains the queue and speaks the verified response.
5. `_deliver_voice_response()` no longer converts a temporary TTS transport outage into a false command failure.

The existing layered anti-echo design remains intact: WebRTC AEC when available, TTS capture gating, and recent-output transcript filtering.

## File viewer
The 0.1 file workspace continues to support full-screen opening for supported text/code, CSV, DOCX, PDF text, and image files without changing the existing UI layout.

## Browser log
A Playwright/Firefox persistent-profile launch error is separate from the Gemini Live TTS failure shown in the supplied log. The voice recovery change prevents that type of unrelated browser failure from causing an already-completed voice command to be reported as a TTS failure.

## Validation
- Python compilation: PASS
- Test suite: **63 passed, 1 skipped**
- UI layout: unchanged
