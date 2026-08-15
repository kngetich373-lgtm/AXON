import unittest
from axon.integrations.meta_messaging import parse_webhook_messages

class MetaWebhookTests(unittest.TestCase):
    def test_whatsapp_message(self):
        payload={"object":"whatsapp_business_account","entry":[{"changes":[{"value":{"messages":[{"from":"254700","id":"wamid.1","timestamp":"1","text":{"body":"hello"}}]}}]}]}
        msgs=parse_webhook_messages(payload)
        self.assertEqual(msgs[0].service,"whatsapp")
        self.assertEqual(msgs[0].text,"hello")

    def test_messenger_message(self):
        payload={"object":"page","entry":[{"messaging":[{"sender":{"id":"psid"},"recipient":{"id":"page"},"message":{"mid":"mid.1","text":"hello"}}]}]}
        msgs=parse_webhook_messages(payload)
        self.assertEqual(msgs[0].service,"meta_messenger")
        self.assertEqual(msgs[0].sender,"psid")

if __name__ == '__main__': unittest.main()
