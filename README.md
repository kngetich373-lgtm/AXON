# AXON V15.2.0

AXON is a Tk desktop AI assistant with multi-provider model catalogs, capability-aware routing, streaming responses, governed desktop actions, local memory, and optional Gemini Live voice.

## Install and run

AXON requires Python 3 with Tk support and a graphical desktop session. From this directory, create an isolated environment explicitly:

```bash
./run.sh --setup-venv
cp .env.example .env
# edit .env and add only the provider keys you want to use
./run.sh
```

`./run.sh` uses `venv/bin/python` when an existing virtual environment is present. It never creates one unless `--setup-venv` is supplied. Without a venv it uses a suitable `python3`/`python` interpreter and prints the exact dependency-install command if packages are missing.

You may instead create an environment manually:

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
./run.sh
```

## V15.2 architecture foundation

V15.2 restores the original gold/glass AXON command-center UI while preserving the V15 Agent, Skills, layered Memory, Knowledge Graph, Security workflows, and external integration architecture.

## V15 architecture foundation

V15 keeps the proven V14 capabilities while introducing modular boundaries for the next AXON OS generation:

- `axon/core/` — Agent, Planner, Executor, Context and Event Bus.
- `axon/tools/` — centralized Tool Registry with risk-aware permissions.
- `axon/security/` — permission policy while retaining the existing security analyzer and governed terminal/file controls.
- `axon/integrations/` — provider-neutral interfaces for future Gmail, WhatsApp, Meta, GitHub, calendar and API integrations.
- `axon/auth/` — authentication contracts for external integrations.
- `axon/planning/` — daily task planning primitives.
- `axon/observability/` — bounded activity records.

The V15 foundation is compatibility-first: existing V14 modules remain in place until each migration is tested.

## Provider configuration

Put keys in the private `.env` file (copy from `.env.example`) or export them in the shell before launch:

```bash
export GEMINI_API_KEY='...'
export OPENAI_API_KEY='...'
./run.sh
```

Supported cloud providers are OpenAI, OpenRouter, Groq, DeepSeek, xAI, Kimi / Moonshot, Anthropic, and Google Gemini. In **Settings → AI Providers**, import each configured provider's live catalog. AXON stores catalog and health data in `axon/data/providers.json`, but deliberately does not persist API keys there; keep `.env` private and do not commit it.

Gemini imports retain `GenerateContent` capability metadata. On launch, older flattened Gemini records are migrated safely: normal `gemini-*`/`gemma-*` text families are recovered only when they are not embedding, AQA, image, video, audio, TTS, deprecated, or retired products. Re-import a catalog if an unfamiliar legacy model needs current capability data.

## Ollama is optional

Ollama is useful for local/private routing but is not required. If `http://127.0.0.1:11434` is unavailable, AXON marks only Ollama offline and continues to route configured cloud chat models. Use **Local Only** or **Private** only when you intentionally require an available local model.

## GUI requirements and headless use

AXON is a desktop application. It must be started from a logged-in graphical Linux session with `DISPLAY` or `WAYLAND_DISPLAY` set. For remote use, connect with `ssh -X` and run a local X server. Starting without a display exits before Tk initializes and prints these instructions instead of a traceback.

There is no terminal-chat mode in this release.

## Routing and reliability

- **Auto**, **Free**, **Auto Coding**, **Auto Fast**, and **Auto Best** route across eligible cloud and local chat models.
- **Local Only** and **Private** restrict routing to Ollama.
- Importing a catalog is separate from proving inference access. **TEST CHAT** performs a small generation probe; **VERIFY ALL CHAT MODELS** is opt-in because it can use provider quota.
- Failed, unauthorized, unavailable, payment-required, and rate-limited models receive a temporary cooldown. The next eligible provider/model is tried automatically.
- Chat streaming buffers an attempt until it has a valid response, so a failed fallback does not mix partial output into the UI.

## Troubleshooting

**“No verified chat model is available”** — add a provider key, import its catalog, then use **TEST CHAT**. Confirm at least one model is shown as routable/ready.

**Ollama shows OFFLINE** — start Ollama if you need local inference (`ollama serve`), or ignore the status and use a configured cloud provider.

**Gemini catalog has no chat candidates after upgrading** — re-open AXON to migrate legacy records, or click **IMPORT** for Google Gemini to fetch current `GenerateContent` metadata.

**No desktop display** — open a terminal inside your desktop session and run `./run.sh`; for SSH use `ssh -X` with a working X server.

**Missing dependencies** — run `./run.sh --setup-venv`, then run `./run.sh` again.

## Security

AXON never logs API-key values. Keep `.env` out of source control, rotate any key that was accidentally exposed, and use provider-level key restrictions where available. Desktop actions remain governed by `axon/tools.py`; model access does not grant arbitrary shell access.

## V15 integrations
See `INTEGRATIONS_V15.md` for Gmail, Google Calendar, WhatsApp Business Cloud API, and Meta Messenger setup.


## V15.3.1 real account connections

- Gmail: official Google OAuth2 connection and inbox reading from Settings.
- WhatsApp personal linked device: persistent WhatsApp Web session with QR linking and read-only chat listing.
- The existing WhatsApp Business Cloud API remains available separately.
- Install Playwright and its browser once: `python -m pip install -r requirements.txt` then `python -m playwright install chromium`.
- WhatsApp Web session data is stored under `~/.config/axon/whatsapp_web` by default.

## AXON 0.1.1 voice reliability

AXON 0.1.1 uses a layered voice anti-echo design. On Kali desktops using PipeWire/PulseAudio with `pactl`, AXON creates a WebRTC acoustic echo-cancellation sink/source pair and routes AXON TTS through the paired playback reference before Gemini receives microphone audio. TTS capture gating and recent-output transcript filtering remain as secondary safeguards.

For the strongest voice experience on Kali, make sure the desktop audio compatibility tools are installed and the session is running under PipeWire/PulseAudio (the `pactl`, `parec`, and `paplay` commands should be available). If AEC is unavailable, AXON automatically falls back to its existing TTS capture gate rather than allowing a self-conversation loop.

The Files & PDFs page now includes **FULL SCREEN** for in-app viewing of supported text/code/CSV/DOCX/PDF/image files. The existing approved-folder security policy remains enforced.
