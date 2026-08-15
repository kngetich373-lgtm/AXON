# AXON V15.7.2 — Voice Reliability + UI

## Fixed
- Replaced the V15.7.1 blue/navy Voice console with the AXON gold/black + purple command-center visual language.
- Added real microphone signal telemetry (RMS/peak) so `LISTENING` is no longer treated as proof that usable microphone audio is arriving.
- Prefer PipeWire/PulseAudio `parec`/`paplay` on Kali desktop systems, with ALSA `arecord`/`aplay` fallback.
- Detect and display the system default microphone source via `pactl` when available.
- Added a MIC TEST action that reports whether real microphone signal reaches AXON.
- Added live microphone meter and backend/source diagnostics.
- Marshalled microphone telemetry back to Tkinter's main thread.
- Preserved the V15.7.1 voice lifecycle fix and all existing security/integration functionality.

## Verification
- `PYTHONPATH=. pytest -q` -> 43 passed, 1 skipped, 5 subtests passed.
- Desktop smoke launch under Xvfb completed without startup exceptions; the smoke process was stopped by timeout.

## Important
AXON cannot prove microphone hardware is working merely because `arecord`/`parec` produces PCM chunks. V15.7.2 exposes actual signal level. If the meter remains near 0%, select/repair the desktop input source or permissions rather than changing Gemini routing blindly.
