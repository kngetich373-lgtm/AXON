# AXON 0.1.4

## Runtime fixes

### Voice engine
- Speech activity without an input transcript is now treated as non-fatal. Gemini Live can report speech activity for short noise, music, or residual AEC audio without returning a transcript; AXON now continues listening instead of emitting a repeated error/reconnect loop.
- Existing TTS capture gating, output-echo filtering, and WebRTC/PipeWire AEC remain active.

### Brave / YouTube playback
- Voice music commands use Brave explicitly instead of Firefox.
- Added a dedicated `youtube_play` browser action.
- The action finds a normal `/watch?v=` result instead of relying on one brittle thumbnail selector.
- Attempts normal YouTube play controls and verifies the HTML5 video element is actually playing before reporting success.
- Playback is only automated for an explicit voice play/listen command; YouTube account, consent, ads, restrictions, and browser policies remain respected.

### Browser session recovery
- Detects closed Chromium contexts even when the Python context object still exists.
- Recreates the persistent browser context when a page/context dies between operations.
- Prevents `BrowserContext.new_page: Target page, context or browser ...` from permanently breaking the browser session.

## Validation
- Python compilation: PASS
- Test suite with `PYTHONPATH=.`: 62 passed, 1 skipped, 5 subtests passed.
- UI/layout: unchanged.
