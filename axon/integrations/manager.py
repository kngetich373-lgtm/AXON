"""Concrete AXON integration bootstrap and tool registration."""
from __future__ import annotations
from .registry import IntegrationRegistry
from .gmail import GmailIntegration
from .google_calendar import GoogleCalendarIntegration
from .meta_messaging import WhatsAppCloudIntegration, MessengerIntegration, parse_webhook_messages
from .message_store import MessageStore
from .whatsapp_web import WhatsAppWebIntegration
from .settings_store import IntegrationSettings

class AXONIntegrations:
    def __init__(self):
        self.settings = IntegrationSettings()
        self.registry = IntegrationRegistry()
        self.gmail = GmailIntegration()
        self.calendar = GoogleCalendarIntegration()
        self.whatsapp = WhatsAppCloudIntegration()
        self.whatsapp_linked = WhatsAppWebIntegration()
        self.messenger = MessengerIntegration()
        self._load_settings()
        self.messages = MessageStore()
        for item in (self.gmail, self.calendar, self.whatsapp, self.messenger):
            self.registry.register(item)


    def _load_settings(self):
        g = self.settings.section("google")
        if g.get("credentials_file"):
            self.gmail.oauth.configure(g.get("credentials_file"), str(__import__("pathlib").Path.home()/".config"/"axon"/"gmail_token.json"))
            self.calendar.oauth.configure(g.get("credentials_file"), str(__import__("pathlib").Path.home()/".config"/"axon"/"calendar_token.json"))
        w = self.settings.section("whatsapp_cloud")
        if w.get("token") and w.get("phone_number_id"):
            self.whatsapp.configure(w["token"], w["phone_number_id"], w.get("waba_id", ""))
        m = self.settings.section("meta_messenger")
        if m.get("token") and m.get("page_id"):
            self.messenger.configure(m["token"], m["page_id"])

    def configure_google(self, credentials_file: str):
        self.settings.save("google", {"credentials_file": credentials_file})
        self.gmail.oauth.configure(credentials_file, str(__import__("pathlib").Path.home()/".config"/"axon"/"gmail_token.json"))
        self.calendar.oauth.configure(credentials_file, str(__import__("pathlib").Path.home()/".config"/"axon"/"calendar_token.json"))

    def configure_whatsapp_cloud(self, token: str, phone_number_id: str, waba_id: str = ""):
        self.settings.save("whatsapp_cloud", {"token": token, "phone_number_id": phone_number_id, "waba_id": waba_id})
        self.whatsapp.configure(token, phone_number_id, waba_id)

    def configure_meta(self, token: str, page_id: str):
        self.settings.save("meta_messenger", {"token": token, "page_id": page_id})
        self.messenger.configure(token, page_id)

    def handle_webhook(self, payload: dict) -> list[dict]:
        parsed = parse_webhook_messages(payload)
        for msg in parsed:
            self.messages.add({"service": msg.service, "conversation_id": msg.conversation_id, "message_id": msg.message_id, "sender": msg.sender, "text": msg.text, "timestamp": msg.timestamp, "read": False})
        return [msg.__dict__ for msg in parsed]

    def status(self) -> dict[str, object]:
        result = {x.info.name: x.is_connected() for x in self.registry.list()}
        result["whatsapp_linked_device"] = self.whatsapp_linked.status()
        return result
