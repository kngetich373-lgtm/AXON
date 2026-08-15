"""Personal WhatsApp linked-device connector using WhatsApp Web in a persistent browser session.

This is intentionally separate from the official WhatsApp Business Cloud API connector.
It requires the user to scan the QR code in WhatsApp > Linked devices.
"""
from __future__ import annotations
from pathlib import Path
import os
import threading
from typing import Any

class WhatsAppWebError(RuntimeError):
    pass

class WhatsAppWebIntegration:
    name = "whatsapp_linked_device"

    def __init__(self, profile_dir: str | None = None):
        self.profile_dir = Path(profile_dir or os.getenv("AXON_WHATSAPP_WEB_PROFILE", str(Path.home()/".config"/"axon"/"whatsapp_web"))).expanduser()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._pw = None
        self._context = None
        self._page = None

    def _ensure(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise WhatsAppWebError("Playwright is required. Run: python -m pip install playwright && python -m playwright install chromium") from exc
        if self._context and not self._context.pages:
            self._context = None
        if self._context is None:
            self._pw = sync_playwright().start()
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=False,
                viewport={"width": 1280, "height": 900},
                args=["--disable-dev-shm-usage"],
            )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self._page

    def connect(self) -> dict[str, Any]:
        with self._lock:
            page = self._ensure()
            if "web.whatsapp.com" not in page.url:
                page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded", timeout=60000)
            return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            if not self._page or self._page.is_closed():
                return {"connected": False, "state": "not_started"}
            url = self._page.url
            # WhatsApp Web exposes the QR/login screen before a linked session.
            try:
                login_visible = self._page.locator('div[data-testid="qrcode"], canvas[aria-label*="QR"], [aria-label*="Scan code"]').count() > 0
            except Exception:
                login_visible = False
            if login_visible:
                return {"connected": False, "state": "awaiting_qr", "url": url}
            try:
                has_chat_list = self._page.locator('div[role="grid"], [aria-label*="Chat list"], [aria-label*="Chats"]').count() > 0
            except Exception:
                has_chat_list = False
            return {"connected": bool(has_chat_list), "state": "connected" if has_chat_list else "opening", "url": url}

    def chats(self, limit: int = 20) -> list[dict[str, str]]:
        with self._lock:
            page = self._require_page()
            if not self.status().get("connected"):
                raise WhatsAppWebError("WhatsApp is not linked yet. Scan the QR code shown in the WhatsApp Web window.")
            rows = page.locator('div[role="grid"] [role="row"]')
            out = []
            for i in range(min(rows.count(), limit)):
                row = rows.nth(i)
                text = row.inner_text().strip()
                if text:
                    out.append({"text": text})
            return out

    def current_messages(self, limit: int = 30) -> list[dict[str, str]]:
        with self._lock:
            page = self._require_page()
            if not self.status().get("connected"):
                raise WhatsAppWebError("WhatsApp is not linked yet.")
            # WhatsApp Web has changed data-testid values over time; copyable-text is
            # intentionally used as a resilient, read-only extraction surface.
            nodes = page.locator('div.copyable-text')
            texts = []
            count = nodes.count()
            for i in range(max(0, count-limit), count):
                txt = nodes.nth(i).inner_text().strip()
                if txt:
                    texts.append({"text": txt})
            return texts

    def disconnect(self) -> None:
        with self._lock:
            try:
                if self._context:
                    self._context.close()
            finally:
                self._context = None
                self._page = None
                if self._pw:
                    try: self._pw.stop()
                    except Exception: pass
                self._pw = None

    def _require_page(self):
        if not self._page or self._page.is_closed():
            raise WhatsAppWebError("Connect WhatsApp Linked Device first from AXON Settings.")
        return self._page
