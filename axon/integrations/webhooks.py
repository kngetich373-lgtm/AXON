"""Minimal HTTPS-ready webhook application for Meta/WhatsApp callbacks.
Run behind a TLS reverse proxy in production. Meta requires HTTPS for production webhooks.
"""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from typing import Callable
from .meta_messaging import verify_meta_signature

class MetaWebhookHandler(BaseHTTPRequestHandler):
    callback: Callable[[dict], None] | None = None

    def do_GET(self):
        mode = self._query("hub.mode")
        token = self._query("hub.verify_token")
        challenge = self._query("hub.challenge")
        expected = os.getenv("AXON_META_WEBHOOK_VERIFY_TOKEN", "")
        if mode == "subscribe" and token and challenge and hmac_compare(token, expected):
            self.send_response(200); self.end_headers(); self.wfile.write(challenge.encode())
            return
        self.send_response(403); self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        secret = os.getenv("AXON_META_APP_SECRET", "")
        if not verify_meta_signature(raw, self.headers.get("X-Hub-Signature-256"), secret):
            self.send_response(401); self.end_headers(); return
        try:
            payload = json.loads(raw.decode("utf-8"))
            if self.callback:
                self.callback(payload)
            self.send_response(200); self.end_headers(); self.wfile.write(b"EVENT_RECEIVED")
        except Exception:
            self.send_response(400); self.end_headers()

    def _query(self, key: str) -> str:
        from urllib.parse import parse_qs, urlparse
        return parse_qs(urlparse(self.path).query).get(key, [""])[0]

def hmac_compare(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a, b)

def start_webhook_server(host: str | None = None, port: int | None = None, callback=None):
    MetaWebhookHandler.callback = callback
    server = ThreadingHTTPServer((host or os.getenv("AXON_WEBHOOK_HOST", "127.0.0.1"), int(port or os.getenv("AXON_WEBHOOK_PORT", "8787"))), MetaWebhookHandler)
    server.daemon_threads = True
    return server
