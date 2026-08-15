# AXON V15.6.0 — Voice Reliability + Voice Console

## Voice reliability
- Fixed Gemini 3.1 Live greeting/input sequencing: realtime text is used instead of send_client_content for normal turns.
- Sends microphone PCM using the official google-genai `types.Blob` path.
- Captures and displays Live API input and output audio transcriptions.
- Adds governed AXON command routing from voice transcripts. Verified local action results are fed back into the Live session for spoken confirmation.
- Adds live diagnostics for microphone, speaker, API key, audio chunks, last heard phrase, and last response.
- Adds an explicit voice response test.

## Voice UI
- Redesigned only the Voice page; other AXON pages remain unchanged.
- Replaced the oversized astral-only presentation with a functional Voice Command Console.
- Added Start/Stop Voice, Test Response, Voice Settings, live transcript, diagnostics, and quick commands.
- Retains AXON gold/black visual identity with purple voice accents.

## Verification
- Python compile check passed after the voice engine and UI changes.
