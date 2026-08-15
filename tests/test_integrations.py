import os
import unittest
from unittest.mock import Mock, patch

from axon.integrations import AXONIntegrations
from axon.integrations.meta_messaging import verify_meta_signature

class IntegrationTests(unittest.TestCase):
    def test_registry_has_real_integrations(self):
        x = AXONIntegrations()
        self.assertIsNotNone(x.registry.get("gmail"))
        self.assertIsNotNone(x.registry.get("google_calendar"))
        self.assertIsNotNone(x.registry.get("whatsapp"))
        self.assertIsNotNone(x.registry.get("meta_messenger"))

    def test_meta_signature(self):
        import hmac, hashlib
        body=b'{"object":"test"}'
        secret="secret"
        sig="sha256="+hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_meta_signature(body,sig,secret))
        self.assertFalse(verify_meta_signature(body,"sha256=bad",secret))

    @patch("axon.integrations.meta_messaging.requests.post")
    def test_whatsapp_send(self, post):
        x=AXONIntegrations().whatsapp
        x.token="token"; x.phone_number_id="123"
        post.return_value.ok=True
        post.return_value.json.return_value={"messages":[{"id":"wamid.1"}]}
        self.assertEqual(x.send_text("254700000000","hello"),"wamid.1")
        self.assertEqual(post.call_args.kwargs["json"]["text"]["body"],"hello")

    @patch("axon.integrations.meta_messaging.requests.post")
    def test_messenger_send(self, post):
        x=AXONIntegrations().messenger
        x.token="token"; x.page_id="page"
        post.return_value.ok=True
        post.return_value.json.return_value={"message_id":"mid.1"}
        self.assertEqual(x.send_text("psid","hello"),"mid.1")

if __name__ == "__main__": unittest.main()
