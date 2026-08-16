# AXON

> **An AI operating system for desktop intelligence, automation, and engineering workflows.**

AXON is a desktop AI platform built around a modular runtime for agents, tools, model routing, memory, security, and external integrations. It is designed to move beyond a chat interface toward an assistant that can **understand, plan, execute, observe, and recover**.

## What AXON does

- **AI assistant** — conversational text and optional voice interaction.
- **Multi-provider routing** — work across supported cloud and local model providers.
- **Agent architecture** — coordinate specialized agents for different tasks.
- **Tool execution** — governed desktop, filesystem, terminal, and application actions.
- **Memory** — maintain useful conversation and long-term context.
- **Security controls** — permission boundaries and safer execution policies.
- **Integrations** — foundations for services such as Gmail, calendar, WhatsApp, GitHub, and external APIs.
- **Observability** — make model, agent, task, and system activity visible.

## Architecture

```text
                         ┌──────────────────┐
                         │     AXON UI      │
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │ System Runtime   │
                         │ / Orchestrator   │
                         └────────┬─────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          ▼                       ▼                       ▼
   Agent Framework          Model Router             Workflow Engine
          │                       │                       │
          ▼                       ▼                       ▼
       Tools              Cloud / Local Models        Task State
          │
          ▼
   Security / Policy
          │
          ├──────── Memory
          ├──────── Event Bus
          └──────── Integrations
```

The architecture is intentionally modular so providers, agents, tools, and integrations can change without rewriting the entire application.

## Provider support

AXON can work with configured providers including OpenAI, OpenRouter, Groq, DeepSeek, xAI, Kimi / Moonshot, Anthropic, Google Gemini, and optional Ollama/local models. Provider catalogs and health information are separated from secret credentials.

### Configure providers

Create your private environment file from the example:

```bash
cp .env.example .env
```

Then add only the credentials you intend to use. **Never commit `.env` or API keys.**

Provider/model availability depends on the credentials and catalogs configured on your machine.

## Quick start

AXON requires Python 3 and a graphical desktop session.

```bash
./run.sh --setup-venv
cp .env.example .env
# edit .env
./run.sh
```

Manual setup:

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
./run.sh
```

For remote graphical sessions, ensure a working display environment is available. AXON is a desktop application rather than a terminal-only chat client.

## Repository layout

```text
AXON/
├── axon/
│   ├── core/             Agent, planner, executor, context, events
│   ├── tools/            Tool registry and governed actions
│   ├── security/         Permission and security policies
│   ├── integrations/     External service interfaces
│   ├── auth/             Authentication contracts
│   ├── planning/         Task planning primitives
│   ├── observability/    Bounded activity and telemetry records
│   └── data/             Local runtime/catalog data
├── tests/                 Automated tests
├── requirements.txt       Python dependencies
├── .env.example           Safe configuration template
└── run.sh                 Application launcher
```

The exact implementation evolves with each AXON release; the module boundaries above describe the architectural intent.

## Reliability model

AXON separates **model discovery** from **inference verification**. A model appearing in a provider catalog does not automatically mean it is available for inference.

Routing can:

- select eligible models based on capabilities;
- avoid unavailable or rate-limited models;
- apply temporary cooldowns after failures;
- fall back to another eligible provider/model;
- preserve clean response boundaries during streaming.

## Local models

Ollama is optional. When unavailable, AXON can continue using configured cloud providers. Use local/private routing only when a local model is intentionally configured and available.

## Security

AXON treats model output as untrusted input.

Security principles include:

- least-privilege tool access;
- explicit permission boundaries for risky actions;
- no API-key logging;
- private environment-based secret management;
- governed terminal and filesystem operations;
- observable automation and failure states.

If a credential is accidentally exposed, revoke/rotate it immediately.

## Development

Install development dependencies in an isolated environment and run the project's automated tests before merging architectural changes.

```bash
pytest
```

For substantial changes, prefer small modular commits and verify both the affected subsystem and its integration points.

## Roadmap direction

AXON is evolving toward a cohesive AI operating environment with:

- stronger autonomous task planning;
- richer agent coordination;
- durable memory and knowledge graphs;
- secure desktop automation;
- voice and vision interaction;
- engineering workspaces;
- broader external integrations;
- stronger observability and recovery loops.

## Project status

AXON is an actively developed project. APIs, UI surfaces, and internal module boundaries may change as the platform moves toward a stable architecture.

## License

See `LICENSE` for the repository's license terms.

---

<div align="center">

**AXON — perceive · reason · act · verify**

</div>
