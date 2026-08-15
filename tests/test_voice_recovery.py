import unittest
from unittest.mock import patch

from axon.gemini_voice import GeminiLiveVoice


class VoiceRecoveryTests(unittest.TestCase):
    def make_voice(self):
        return GeminiLiveVoice("key", lambda *_: None, lambda *_: None)

    def test_send_text_queues_and_recovers_when_supervisor_is_dead(self):
        v = self.make_voice()
        with patch.object(type(v), "available", new=property(lambda _self: True)), \
             patch.object(v, "_thread_main") as thread_main:
            self.assertTrue(v.send_text("Speak the verified result"))
            thread_main.assert_called_once()
        self.assertEqual(v._pending_tts_texts, ["Speak the verified result"])

    def test_send_text_returns_false_for_empty_text(self):
        v = self.make_voice()
        self.assertFalse(v.send_text("   "))
        self.assertEqual(v._pending_tts_texts, [])

    def test_send_text_preserves_queue_during_active_reconnect(self):
        v = self.make_voice()
        v.running = True
        v.loop = None
        self.assertTrue(v.send_text("queued during reconnect"))
        self.assertEqual(v._pending_tts_texts, ["queued during reconnect"])

    def test_send_text_preserves_queue_when_loop_is_closed(self):
        v = self.make_voice()
        v.running = True
        v.loop = None
        self.assertTrue(v.send_text("queued for next session"))
        self.assertEqual(v._pending_tts_texts, ["queued for next session"])


if __name__ == "__main__":
    unittest.main()
