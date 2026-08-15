#!/usr/bin/env python3
"""Run AXON's Meta/WhatsApp webhook listener.
Put a real HTTPS reverse proxy/tunnel in front of this listener for Meta production callbacks.
"""
from axon.integrations import AXONIntegrations
from axon.integrations.webhooks import start_webhook_server

integrations = AXONIntegrations()
server = start_webhook_server(callback=integrations.handle_webhook)
print(f"AXON webhook listener on {server.server_address[0]}:{server.server_address[1]}")
print("Configure Meta/WhatsApp callback URL to / and use your verify token.")
try:
    server.serve_forever()
except KeyboardInterrupt:
    server.shutdown()
