# AXON V14.0.3

## Connectivity hotfix

This release fixes a critical routing issue discovered in V14.0.2 where imported legacy OpenAI models such as `gpt-3.5-turbo` could remain marked as routable and be selected by Auto routing.

### Changes
- Legacy/non-chat OpenAI catalog entries are quarantined from normal routing.
- Existing model catalogs are reclassified at startup so stale `routable=true` flags are corrected.
- An explicitly selected legacy/failed model can no longer override the router's fallback system.
- Streaming now tries the next candidate when a model fails.
- OpenAI streaming supports Responses API with Chat Completions fallback.
- Streaming output is buffered per attempt so a failed attempt cannot duplicate partial text in the UI.
- HTTP 402, 401/403 and 429 errors are classified and remembered per model.
- Candidate routing skips models marked FAILED, AUTH ERROR, RATE LIMITED, PAYMENT REQUIRED or OFFLINE.
- Provider/model counts remain visible, while runtime routing is based on actual eligible chat models.

## Expected behavior

If OpenAI contains old models such as:

- `gpt-3.5-turbo`
- `gpt-3.5-turbo-0125`
- `text-davinci-*`

AXON may still display them in the imported catalog, but it will not automatically route normal conversations to them.

If one provider returns 402/401/403/429/404 or an empty stream, AXON records that model's failure and tries the next eligible provider/model.
