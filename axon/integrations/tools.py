"""Tool Registry adapters for real external integrations."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from axon.actions import ActionResult
from axon.security import Risk


def register_integration_tools(registry, integrations) -> None:
    registry.register(name="gmail.search", description="Search the connected Gmail mailbox.", handler=lambda query, context=None, **_: _ok(integrations.gmail.search(query)), risk=Risk.LOW, requires_confirmation=False)
    registry.register(name="gmail.read", description="Read a Gmail message by ID.", handler=lambda message_id, context=None, **_: _ok(integrations.gmail.get_message(message_id)), risk=Risk.LOW, requires_confirmation=False)
    registry.register(name="gmail.draft", description="Create a Gmail draft.", handler=lambda to, subject, body, context=None, **_: _ok(integrations.gmail.draft(to, subject, body)), risk=Risk.MEDIUM, requires_confirmation=False)
    registry.register(name="gmail.send", description="Send an email through Gmail.", handler=lambda to, subject, body, context=None, **_: _ok(integrations.gmail.send(to, subject, body)), risk=Risk.HIGH, requires_confirmation=True)
    registry.register(name="gmail.reply", description="Reply to a Gmail message.", handler=lambda message_id, body, context=None, **_: _ok(integrations.gmail.reply(message_id, body)), risk=Risk.HIGH, requires_confirmation=True)

    registry.register(name="calendar.list", description="List Google Calendar events for a time range.", handler=lambda start, end, context=None, **_: _ok(integrations.calendar.list_events(_dt(start), _dt(end))), risk=Risk.LOW, requires_confirmation=False)
    registry.register(name="calendar.create", description="Create a Google Calendar event.", handler=lambda title, start, end, context=None, **_: _ok(integrations.calendar.create_event(_event(title, start, end))), risk=Risk.HIGH, requires_confirmation=True)
    registry.register(name="calendar.delete", description="Delete a Google Calendar event.", handler=lambda event_id, context=None, **_: _ok(integrations.calendar.delete_event(event_id)), risk=Risk.HIGH, requires_confirmation=True)

    registry.register(name="whatsapp_linked.status", description="Report the real state of the WhatsApp Web linked-device session.", handler=lambda context=None, **_: _ok(integrations.whatsapp_linked.status()), risk=Risk.LOW, requires_confirmation=False)
    registry.register(name="whatsapp_linked.connect", description="Open WhatsApp Web for QR-code linked-device authentication.", handler=lambda context=None, **_: _ok(integrations.whatsapp_linked.connect()), risk=Risk.MEDIUM, requires_confirmation=True)
    registry.register(name="whatsapp_linked.chats", description="Read visible WhatsApp chats from the linked-device session.", handler=lambda limit=20, context=None, **_: _ok(integrations.whatsapp_linked.chats(int(limit))), risk=Risk.LOW, requires_confirmation=False)
    registry.register(name="whatsapp_linked.messages", description="Read messages visible in the currently open WhatsApp chat.", handler=lambda limit=30, context=None, **_: _ok(integrations.whatsapp_linked.current_messages(int(limit))), risk=Risk.LOW, requires_confirmation=False)
    registry.register(name="whatsapp.inbox", description="List received WhatsApp webhook messages.", handler=lambda context=None, **_: _ok(integrations.messages.list("whatsapp")), risk=Risk.LOW, requires_confirmation=False)
    registry.register(name="meta.inbox", description="List received Meta Messenger webhook messages.", handler=lambda context=None, **_: _ok(integrations.messages.list("meta_messenger")), risk=Risk.LOW, requires_confirmation=False)
    registry.register(name="whatsapp.send", description="Send a WhatsApp Business message.", handler=lambda recipient, body, context=None, **_: _ok(integrations.whatsapp.send_text(recipient, body)), risk=Risk.HIGH, requires_confirmation=True)
    registry.register(name="whatsapp.subscribe", description="Subscribe the WhatsApp Business Account to webhook events.", handler=lambda context=None, **_: _ok(integrations.whatsapp.subscribe()), risk=Risk.HIGH, requires_confirmation=True)
    registry.register(name="meta.send", description="Send a Messenger message from the connected Facebook Page.", handler=lambda recipient_psid, body, context=None, **_: _ok(integrations.messenger.send_text(recipient_psid, body)), risk=Risk.HIGH, requires_confirmation=True)
    registry.register(name="meta.subscribe", description="Subscribe the Facebook Page to Messenger webhook events.", handler=lambda context=None, **_: _ok(integrations.messenger.subscribe()), risk=Risk.HIGH, requires_confirmation=True)

def _ok(value):
    return ActionResult.success("Integration operation completed.", result=value)

def _dt(value):
    if isinstance(value, datetime): return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

def _event(title, start, end):
    from .calendar import CalendarEvent
    return CalendarEvent(title, _dt(start), _dt(end))
