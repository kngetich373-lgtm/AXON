"""Official Meta Graph API clients for WhatsApp Cloud API and Messenger Pages."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import hashlib
import hmac
import os
import requests

from .base import Integration, IntegrationInfo

GRAPH_VERSION = os.getenv("AXON_META_GRAPH_VERSION", "v23.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

@dataclass(frozen=True)
class RemoteMessage:
    service: str
    conversation_id: str
    message_id: str
    sender: str | None
    text: str | None
    timestamp: str | None = None

class WhatsAppCloudIntegration(Integration):
    info = IntegrationInfo("whatsapp", "WhatsApp Business Platform Cloud API integration", ("whatsapp_business_messaging",))
    def __init__(self, token: str | None = None, phone_number_id: str | None = None, waba_id: str | None = None):
        self.token = token or os.getenv("AXON_WHATSAPP_TOKEN", "")
        self.phone_number_id = phone_number_id or os.getenv("AXON_WHATSAPP_PHONE_NUMBER_ID", "")
        self.waba_id = waba_id or os.getenv("AXON_WHATSAPP_WABA_ID", "")

    def is_connected(self) -> bool:
        if not self.token or not self.phone_number_id:
            return False
        r = requests.get(f"{GRAPH_BASE}/{self.phone_number_id}", params={"access_token": self.token, "fields": "id,display_phone_number,verified_name"}, timeout=20)
        return r.ok

    def configure(self, token: str, phone_number_id: str, waba_id: str = ""):
        self.token, self.phone_number_id, self.waba_id = token.strip(), phone_number_id.strip(), waba_id.strip()

    def disconnect(self) -> None:
        self.token = ""

    def send_text(self, recipient: str, text: str, preview_url: bool = False) -> str:
        self._require()
        payload = {"messaging_product": "whatsapp", "to": recipient, "type": "text", "text": {"body": text, "preview_url": preview_url}}
        r = requests.post(f"{GRAPH_BASE}/{self.phone_number_id}/messages", headers={"Authorization": f"Bearer {self.token}"}, json=payload, timeout=20)
        _raise_graph(r)
        return r.json()["messages"][0]["id"]

    def mark_read(self, message_id: str) -> None:
        self._require()
        payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
        r = requests.post(f"{GRAPH_BASE}/{self.phone_number_id}/messages", headers={"Authorization": f"Bearer {self.token}"}, json=payload, timeout=20)
        _raise_graph(r)

    def subscribe(self) -> dict[str, Any]:
        self._require()
        if not self.waba_id:
            raise RuntimeError("AXON_WHATSAPP_WABA_ID is required to subscribe webhook events")
        r = requests.post(f"{GRAPH_BASE}/{self.waba_id}/subscribed_apps", headers={"Authorization": f"Bearer {self.token}"}, timeout=20)
        _raise_graph(r)
        return r.json()

    def _require(self):
        if not self.token or not self.phone_number_id:
            raise RuntimeError("Set AXON_WHATSAPP_TOKEN and AXON_WHATSAPP_PHONE_NUMBER_ID")

class MessengerIntegration(Integration):
    info = IntegrationInfo("meta_messenger", "Meta Messenger Platform Page messaging integration", ("pages_messaging", "pages_manage_metadata"))
    def __init__(self, token: str | None = None, page_id: str | None = None):
        self.token = token or os.getenv("AXON_META_PAGE_ACCESS_TOKEN", "")
        self.page_id = page_id or os.getenv("AXON_META_PAGE_ID", "")

    def is_connected(self) -> bool:
        if not self.token or not self.page_id:
            return False
        r = requests.get(f"{GRAPH_BASE}/{self.page_id}", params={"access_token": self.token, "fields": "id,name"}, timeout=20)
        return r.ok

    def configure(self, token: str, page_id: str):
        self.token, self.page_id = token.strip(), page_id.strip()

    def disconnect(self) -> None:
        self.token = ""

    def send_text(self, recipient_psid: str, text: str) -> str:
        self._require()
        payload = {"recipient": {"id": recipient_psid}, "message": {"text": text}}
        r = requests.post(f"{GRAPH_BASE}/me/messages", params={"access_token": self.token}, json=payload, timeout=20)
        _raise_graph(r)
        return r.json().get("message_id", "")

    def subscribe(self) -> dict[str, Any]:
        self._require()
        r = requests.post(f"{GRAPH_BASE}/{self.page_id}/subscribed_apps", params={"access_token": self.token, "subscribed_fields": "messages,messaging_postbacks"}, timeout=20)
        _raise_graph(r)
        return r.json()

    def _require(self):
        if not self.token or not self.page_id:
            raise RuntimeError("Set AXON_META_PAGE_ACCESS_TOKEN and AXON_META_PAGE_ID")

def verify_meta_signature(raw_body: bytes, signature: str | None, app_secret: str) -> bool:
    if not signature or not signature.startswith("sha256=") or not app_secret:
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

def _raise_graph(response: requests.Response) -> None:
    if not response.ok:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise RuntimeError(f"Meta API error ({response.status_code}): {detail}")


def parse_webhook_messages(payload: dict) -> list[RemoteMessage]:
    """Normalize supported WhatsApp and Messenger webhook message events."""
    out = []
    obj = payload.get("object")
    if obj == "whatsapp_business_account":
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for m in value.get("messages", []):
                    text = (m.get("text") or {}).get("body")
                    out.append(RemoteMessage("whatsapp", m.get("from", ""), m.get("id", ""), m.get("from"), text, m.get("timestamp")))
    elif obj == "page":
        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                message = event.get("message") or {}
                if message.get("mid") and message.get("text") is not None:
                    sender = (event.get("sender") or {}).get("id")
                    recipient = (event.get("recipient") or {}).get("id")
                    out.append(RemoteMessage("meta_messenger", recipient or "", message.get("mid", ""), sender, message.get("text"), str(event.get("timestamp", ""))))
    return out
