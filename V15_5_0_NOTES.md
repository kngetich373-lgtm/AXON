# AXON V15.5.0

## UI / UX
- Preserves the V15 gold/black AXON command-center identity.
- Compact Home greeting/hero so the conversation receives most of the viewport.
- User chat bubbles are purple; AXON responses use a dark gold-accented bubble.
- Tiny per-response copy button remains available for every AXON response.
- Compact whole-conversation copy button remains in the chat header.
- Conversation scrolling remains touchpad/mouse-wheel friendly and avoids oversized nested chat regions.
- Composer actions remain available: attach, refine, auto, voice, send.

## Settings
- AI Providers retained and redesigned as a compact horizontal table.
- Provider rows retain SAVE, IMPORT, TEST actions and live health states.
- Connected Models are displayed in a compact scrollable text catalog with provider, model type and capability flags.
- AXON Routing remains connected to provider profiles.
- Gemini Live Voice and Voice Profile remain configurable.
- Real Account Integrations retain Gmail, Google Calendar, WhatsApp linked device, WhatsApp Business Cloud and Meta Messenger actions.
- Integration credentials remain outside AXON memory according to the existing integration store.

## Verification
- Python compile check passed.
- 38 tests passed, 5 subtests passed.
- Home and Settings Tk pages instantiated successfully under Xvfb.
- Purple user bubble, gold assistant bubble and individual clipboard copy were smoke-tested.
