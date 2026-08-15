# AXON V15 real integrations

AXON V15 now contains real provider clients for:

- Gmail API (OAuth 2.0): search/read/draft/send/reply.
- Google Calendar API (OAuth 2.0): list/create/update/delete events.
- WhatsApp Business Platform Cloud API: send text, mark read, WABA webhook subscription, inbound webhook normalization.
- Meta Messenger Platform for Facebook Pages: send text, Page webhook subscription, inbound webhook normalization.

## Google setup

1. Create a Google Cloud project.
2. Enable Gmail API and Google Calendar API.
3. Configure Google Auth Platform/OAuth consent screen.
4. Create a Desktop OAuth client and download its JSON credentials.
5. Put the file at `credentials.json` or set `AXON_GOOGLE_CREDENTIALS`.
6. Install dependencies from `requirements.txt`.
7. The first Gmail/Calendar operation opens a browser for OAuth and stores the refresh token under `~/.config/axon/google_token.json` by default.

AXON uses the `gmail.modify` scope for mailbox read/compose/send operations and `calendar.events` for calendar event management. Use narrower scopes if your deployment only needs read-only access.

## WhatsApp setup

Set:

- `AXON_WHATSAPP_TOKEN`
- `AXON_WHATSAPP_PHONE_NUMBER_ID`
- `AXON_WHATSAPP_WABA_ID`
- `AXON_META_APP_SECRET`
- `AXON_META_WEBHOOK_VERIFY_TOKEN`

Then run `python scripts/axon_integrations_webhook.py` and expose it through a publicly reachable HTTPS endpoint. Subscribe the WABA to webhook events.

## Meta Messenger setup

Set:

- `AXON_META_PAGE_ACCESS_TOKEN`
- `AXON_META_PAGE_ID`
- `AXON_META_APP_SECRET`
- `AXON_META_WEBHOOK_VERIFY_TOKEN`

Configure the Messenger webhook for `messages` and connect the app to the Facebook Page. Use the webhook listener for inbound messages.

## Safety

Read/search/inbox operations are low risk. Drafting is medium risk. Sending messages and modifying/deleting calendar events are registered as high risk and require AXON confirmation through the Tool Registry.

Do not put OAuth refresh tokens, access tokens, page tokens, app secrets, or WhatsApp tokens in source control. Use `.env`/a secure secret store and keep permissions restricted.

Meta production webhooks must use HTTPS and valid TLS. The included listener is intentionally a small HTTP backend suitable behind a reverse proxy or secure tunnel.
