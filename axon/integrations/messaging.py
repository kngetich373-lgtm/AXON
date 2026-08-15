"""Common messaging/mail operation contract for future integrations."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class MessageRef:
    service: str
    conversation_id: str
    message_id: str
    sender: str | None = None
    subject: str | None = None

class MessagingIntegration(Protocol):
    def search(self, query: str) -> list[MessageRef]: ...
    def read(self, ref: MessageRef) -> str: ...
    def draft(self, ref: MessageRef, body: str) -> str: ...
    def send(self, conversation_id: str, body: str) -> MessageRef: ...
