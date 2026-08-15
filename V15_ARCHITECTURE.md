# AXON V15 Architecture

AXON V15 is a compatibility-first modular architecture for the existing AXON Kali Linux desktop AI system.

## Core flow

`User -> Agent -> Context -> Router/Planner -> Permission -> Tool Registry -> Existing capability -> Result -> Event/Memory -> User`

V15 deliberately keeps the working V14 modules in place while adding stable boundaries around them. This allows gradual migration instead of a risky rewrite.

## New boundaries

- `axon/core/` — Agent, planning, execution, context, events.
- `axon/tools/` — capability registry; existing tools remain compatible during migration.
- `axon/security/` — centralized permission policy.
- `axon/integrations/` — provider-neutral external-service boundary for future Gmail, WhatsApp, Meta, GitHub, calendars and APIs.
- `axon/planning/` — deterministic daily/task planning primitives.
- `axon/observability/` — bounded activity/event records.

## Compatibility policy

Existing V14 modules remain available until each migration is tested. No provider, voice, memory, browser, filesystem, Kali, or governed-action feature is removed by the V15 foundation.

## Security policy

The new permission layer is advisory until an existing UI confirmation path is connected to it. Existing V14 command/file/action restrictions remain authoritative. V15 must never use model output as unrestricted shell access.

## V15.1 knowledge, skills, memory and security layers

- `axon/skills/` implements discoverable `SKILL.md` workflows.
- `axon/memory/` provides layered L0-L3 memory while preserving the V14 Memory API.
- `axon/knowledge/` provides a deterministic Python AST code graph without executing project code.
- `axon/security/workflows/` provides explicit authorized scope, evidence and findings primitives.
- `axon/security/agents/` provides evidence-first review without direct tool execution.
