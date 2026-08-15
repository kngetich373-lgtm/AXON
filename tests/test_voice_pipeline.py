"""Deterministic voice-pipeline tests; no microphone, Gemini key, or display needed."""
import asyncio
import threading
import time
import unittest
from unittest.mock import Mock
from types import SimpleNamespace

from axon.app import AXONApp
from axon.gemini_voice import GeminiLiveVoice


class _Responses:
    def __init__(self, responses):
        self.responses = responses
        self.used = False

    def receive(self):
        if self.used:
            async def empty():
                if False:
                    yield None
            return empty()
        self.used = True
        async def iterator():
            for response in self.responses:
                yield response
        return iterator()


class _TurnResponses:
    def __init__(self, turns):
        self.turns = list(turns)

    def receive(self):
        responses = self.turns.pop(0) if self.turns else []
        async def iterator():
            for response in responses:
                yield response
        return iterator()


class VoicePipelineTests(unittest.TestCase):
    def test_unexpected_live_session_end_reconnects_instead_of_crashing(self):
        states, calls = [], []
        voice = GeminiLiveVoice("key", lambda _text: None, states.append)
        voice.running = True
        voice._stopping = False
        voice._reconnect_event.wait = Mock(return_value=False)

        async def unstable_session():
            calls.append("run")
            if len(calls) == 1:
                raise RuntimeError("temporary websocket loss")
            voice.running = False

        voice._run = unstable_session
        voice._thread_main()

        self.assertEqual(calls, ["run", "run"])
        self.assertTrue(any(state.startswith("RECONNECTING") for state in states))
        self.assertIn("temporary websocket loss", voice.last_error)

    def test_speaker_write_failure_recovers_without_ending_voice_session(self):
        voice = GeminiLiveVoice("key", lambda _text: None, lambda _state: None)
        voice.running = True
        voice._stopping = False
        voice._speaker = SimpleNamespace(
            poll=lambda: None,
            stdin=SimpleNamespace(write=lambda _data: (_ for _ in ()).throw(BrokenPipeError("closed")), flush=lambda: None),
        )
        voice._clear_speaker = Mock()

        voice._write_speaker(b"pcm")

        voice._clear_speaker.assert_called_once()
        self.assertIn("Speaker write failed", voice.last_error)

    def test_interruption_flag_does_not_clear_continuous_playback(self):
        voice = GeminiLiveVoice("key", lambda _text: None, lambda _state: None)
        voice.running = True
        voice._stop_event = asyncio.Event()
        voice._clear_speaker = Mock()
        responses = _Responses([SimpleNamespace(server_content=SimpleNamespace(
            interrupted=True, input_transcription=None, output_transcription=None, model_turn=None,
            turn_complete=False))])

        asyncio.run(voice._receive_audio(responses))

        voice._clear_speaker.assert_not_called()

    def test_unsolicited_live_audio_is_never_played(self):
        voice = GeminiLiveVoice("key", lambda _text: None, lambda _state: None)
        voice.running = True
        voice._stop_event = asyncio.Event()
        voice._write_speaker = Mock()
        audio_part = SimpleNamespace(inline_data=SimpleNamespace(data=b"unsolicited"))
        responses = _Responses([SimpleNamespace(server_content=SimpleNamespace(
            interrupted=False, input_transcription=None, output_transcription=None,
            model_turn=SimpleNamespace(parts=[audio_part]), turn_complete=False))])

        asyncio.run(voice._receive_audio(responses))

        voice._write_speaker.assert_not_called()

    def test_transcription_during_tts_is_not_accepted_as_user_input(self):
        finals = []
        voice = GeminiLiveVoice("key", finals.append, lambda _state: None)
        voice.running = True
        voice._tts_active = True
        voice._stop_event = asyncio.Event()
        responses = _Responses([SimpleNamespace(server_content=SimpleNamespace(
            interrupted=False, input_transcription=SimpleNamespace(text="AXON's own reply"),
            output_transcription=None, model_turn=None, turn_complete=True))])

        asyncio.run(voice._receive_audio(responses))

        self.assertEqual(finals, [])

    def test_recent_tts_echo_is_filtered(self):
        voice = GeminiLiveVoice("key", lambda _text: None, lambda _state: None)
        voice._last_spoken_fingerprint = voice._fingerprint_text("The scan completed successfully")
        voice._last_spoken_at = time.monotonic()
        self.assertTrue(voice._is_recent_output_echo("The scan completed successfully"))
        self.assertFalse(voice._is_recent_output_echo("Please scan the local network"))

    def test_tts_turn_complete_releases_capture_gate_even_without_audio(self):
        finals = []
        voice = GeminiLiveVoice("key", finals.append, lambda _state: None)
        voice.running = True
        voice._tts_request_inflight = True
        voice._tts_response_started = False
        voice._stop_event = asyncio.Event()
        responses = _Responses([SimpleNamespace(server_content=SimpleNamespace(
            interrupted=False, input_transcription=None, output_transcription=None, model_turn=None, turn_complete=True))])
        asyncio.run(voice._receive_audio(responses))
        self.assertFalse(voice._tts_request_inflight)
        self.assertFalse(voice._tts_response_started)

    def test_partial_input_is_merged_and_only_final_turn_is_submitted(self):
        partials, finals = [], []
        voice = GeminiLiveVoice("key", finals.append, lambda _state: None)
        voice.set_input_transcript_callbacks(partials.append, None)
        voice.running = True
        voice._stop_event = asyncio.Event()
        responses = _Responses([
            SimpleNamespace(server_content=SimpleNamespace(
                input_transcription=SimpleNamespace(text="What is the current"),
                output_transcription=None, model_turn=None, interrupted=False, turn_complete=False)),
            SimpleNamespace(server_content=SimpleNamespace(
                input_transcription=SimpleNamespace(text="What is the current time?"),
                output_transcription=None, model_turn=None, interrupted=False, turn_complete=False)),
            SimpleNamespace(server_content=SimpleNamespace(
                input_transcription=None, output_transcription=None, model_turn=None,
                interrupted=False, turn_complete=True)),
        ])
        asyncio.run(voice._receive_audio(responses))
        self.assertEqual(finals, ["What is the current time?"])
        self.assertEqual(partials[-1], "What is the current time?")

    def test_receiver_stays_on_same_session_across_complete_turns(self):
        finals = []
        voice = GeminiLiveVoice("key", finals.append, lambda _state: None)
        voice.running = True
        voice._stop_event = asyncio.Event()
        turn = lambda text: [
            SimpleNamespace(server_content=SimpleNamespace(input_transcription=SimpleNamespace(text=text), output_transcription=None, model_turn=None, interrupted=False, turn_complete=False)),
            SimpleNamespace(server_content=SimpleNamespace(input_transcription=None, output_transcription=None, model_turn=None, interrupted=False, turn_complete=True)),
        ]
        asyncio.run(voice._receive_audio(_TurnResponses([turn("Hello"), turn("What time is it")])))
        self.assertEqual(finals, ["Hello", "What time is it"])

    def test_duplicate_final_turn_is_suppressed_before_routing(self):
        finals = []
        voice = GeminiLiveVoice("key", finals.append, lambda _state: None)
        voice._input_transcript_buffer = "Play Unity by Alan Walker"
        voice._finalize_input_turn()
        voice._input_transcript_buffer = "Play Unity by Alan Walker"
        voice._finalize_input_turn()

        self.assertEqual(finals, ["Play Unity by Alan Walker"])
        self.assertEqual(voice.duplicate_turns_ignored, 1)

    def test_voice_accepts_only_english_and_kiswahili_language_codes(self):
        self.assertTrue(GeminiLiveVoice._voice_language_supported("en-US"))
        self.assertTrue(GeminiLiveVoice._voice_language_supported("sw-KE"))
        self.assertFalse(GeminiLiveVoice._voice_language_supported("fr-FR"))

    def test_kiswahili_voice_tasks_use_existing_router_intents(self):
        self.assertEqual(AXONApp._normalise_voice_command("Cheza muziki wa Sauti Sol"), "play muziki wa Sauti Sol")
        self.assertEqual(AXONApp._normalise_voice_command("Tafuta mtandaoni hali ya hewa Nairobi"), "search the web for hali ya hewa Nairobi")
        self.assertEqual(AXONApp._normalise_voice_command("Fungua terminali"), "open terminal")
        self.assertEqual(AXONApp._normalise_voice_command("Angalia hali ya mfumo"), "check system status")

    def test_voice_music_uses_standard_youtube_search_url(self):
        url = AXONApp._youtube_search_url("mbaret 2")
        self.assertEqual(url, "https://www.youtube.com/results?search_query=mbaret+2")
        self.assertNotIn("music.youtube.com", url)

    def test_voice_reply_uses_one_matching_supported_language(self):
        self.assertEqual(AXONApp._voice_reply_language("Hello AXON"), "English")
        self.assertEqual(AXONApp._voice_reply_language("Habari AXON, saa ngapi"), "Kiswahili")

    def test_each_final_command_uses_router_and_configured_tts(self):
        submitted, spoken, displayed = [], [], []
        app = AXONApp.__new__(AXONApp)
        app.router = SimpleNamespace(
            route=lambda text, _ui: None,
            stream_answer=lambda text, _token: (f"actual response for {text}", "test", "test"),
        )
        app.memory = SimpleNamespace(record=lambda *args: None)
        app.gemini_voice = SimpleNamespace(send_text=lambda text: spoken.append(text) or True)
        app._voice_command_lock = threading.Lock()
        app.after = lambda _delay, callback: callback()
        app._record_voice_assistant = lambda text: displayed.append(text)

        commands = [
            "What is the current time?", "Open the terminal.", "Check system status.",
            "What files are in my home directory?", "Explain what AXON is.",
        ]
        for command in commands:
            app._govern_voice_command(command)
            submitted.append(command)

        self.assertEqual(len(displayed), len(commands))
        self.assertEqual(len(spoken), len(commands))
        for command, response in zip(commands, displayed):
            self.assertIn(command, response)
