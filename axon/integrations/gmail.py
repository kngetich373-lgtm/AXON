"""Real Gmail integration using Google's official Gmail API and OAuth2."""
from __future__ import annotations
from dataclasses import dataclass
from email.message import EmailMessage
import base64
import os
from typing import Any

from .base import Integration, IntegrationInfo
from .google_oauth import GoogleOAuth

GMAIL_SCOPES = ("https://www.googleapis.com/auth/gmail.modify",)

@dataclass(frozen=True)
class GmailMessage:
    id: str
    thread_id: str | None
    sender: str | None
    to: str | None
    subject: str | None
    snippet: str | None
    body: str

class GmailIntegration(Integration):
    info = IntegrationInfo("gmail", "Gmail mailbox, search, read, draft and send integration", GMAIL_SCOPES)

    def __init__(self, oauth: GoogleOAuth | None = None):
        self.oauth = oauth or GoogleOAuth(token_file=str(__import__("pathlib").Path.home()/".config"/"axon"/"gmail_token.json"))
        self._service = None

    def _api(self):
        if self._service is None:
            try:
                from googleapiclient.discovery import build
            except ImportError as exc:
                raise RuntimeError("Install Google API dependencies before using Gmail.") from exc
            self._service = build("gmail", "v1", credentials=self.oauth.credentials(GMAIL_SCOPES), cache_discovery=False)
        return self._service

    def is_connected(self) -> bool:
        try:
            self._api().users().getProfile(userId="me").execute()
            return True
        except Exception:
            return False

    def disconnect(self) -> None:
        self._service = None
        self.oauth.revoke()

    def profile(self) -> dict[str, Any]:
        return self._api().users().getProfile(userId="me").execute()

    def search(self, query: str, max_results: int = 20) -> list[GmailMessage]:
        result = self._api().users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        return [self.get_message(x["id"]) for x in result.get("messages", [])]

    def list_inbox(self, max_results: int = 20) -> list[GmailMessage]:
        return self.search("in:inbox", max_results)

    def get_message(self, message_id: str) -> GmailMessage:
        data = self._api().users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in data.get("payload", {}).get("headers", [])}
        return GmailMessage(message_id, data.get("threadId"), headers.get("from"), headers.get("to"), headers.get("subject"), data.get("snippet"), _decode_body(data.get("payload", {})))

    def draft(self, to: str, subject: str, body: str, *, in_reply_to: GmailMessage | None = None) -> str:
        msg = self._build_message(to, subject, body, in_reply_to)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        draft = self._api().users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        return draft["id"]

    def send(self, to: str, subject: str, body: str, *, in_reply_to: GmailMessage | None = None) -> str:
        msg = self._build_message(to, subject, body, in_reply_to)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        sent = self._api().users().messages().send(userId="me", body={"raw": raw}).execute()
        return sent["id"]

    def reply(self, message_id: str, body: str) -> str:
        original = self.get_message(message_id)
        if not original.sender:
            raise ValueError("Original message has no sender address")
        subject = original.subject or ""
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        return self.send(original.sender, subject, body, in_reply_to=original)

    def _build_message(self, to: str, subject: str, body: str, original: GmailMessage | None) -> EmailMessage:
        msg = EmailMessage()
        msg.set_content(body)
        msg["To"] = to
        msg["Subject"] = subject
        if original:
            raw = self.get_raw_headers(original.id)
            if raw.get("message-id"):
                msg["In-Reply-To"] = raw["message-id"]
                msg["References"] = raw["message-id"]
        return msg

    def get_raw_headers(self, message_id: str) -> dict[str, str]:
        data = self._api().users().messages().get(userId="me", id=message_id, format="metadata", metadataHeaders=["Message-ID", "References"]).execute()
        return {h["name"].lower(): h["value"] for h in data.get("payload", {}).get("headers", [])}

def _decode_body(payload: dict[str, Any]) -> str:
    body = payload.get("body", {}).get("data")
    if body:
        return base64.urlsafe_b64decode(body + "===").decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        text = _decode_body(part)
        if text:
            return text
    return ""
