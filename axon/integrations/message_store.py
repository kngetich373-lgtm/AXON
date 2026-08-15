"""Small durable store for incoming external messages received by webhooks."""
from __future__ import annotations
import json
from pathlib import Path
from threading import Lock
from typing import Any
from axon.config import DATA

class MessageStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or DATA / "integration_messages.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def add(self, message: dict[str, Any]) -> None:
        with self._lock:
            items = self.list()
            items.append(message)
            self.path.write_text(json.dumps(items[-2000:], ensure_ascii=False, indent=2), encoding="utf-8")

    def list(self, service: str | None = None, unread_only: bool = False) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            items = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if service:
            items = [x for x in items if x.get("service") == service]
        if unread_only:
            items = [x for x in items if not x.get("read")]
        return items

    def mark_read(self, message_id: str) -> bool:
        with self._lock:
            items = self.list()
            changed = False
            for item in items:
                if item.get("message_id") == message_id:
                    item["read"] = True; changed = True
            if changed:
                self.path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            return changed
