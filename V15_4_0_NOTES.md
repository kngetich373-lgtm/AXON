# AXON V15.4.0

Functional integration and UI-preserving maintenance release.

- Runtime capability audit is deterministic and uses actual runtime state.
- Gmail and Google Calendar use official Google OAuth with separate token files.
- Settings can configure Google OAuth credentials, WhatsApp Cloud, and Meta Messenger.
- WhatsApp linked-device remains a persistent Playwright session with QR pairing.
- Knowledge Graph supports deterministic dependency/relationship queries after indexing.
- Agent preserves layered-memory context instead of overwriting it with legacy memory.
- Home greeting/hero is compacted to expose more conversation without redesigning the UI.
- Every AXON assistant response has a tiny per-message copy control.
