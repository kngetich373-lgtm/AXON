"""AXON V14 Gemini Live voice engine.

V14 deliberately keeps microphone/speaker ownership outside PyAudio. On Kali,
Linux-native `arecord`/`aplay` subprocesses are used so native audio resources
have an explicit process boundary and cannot corrupt the Python heap.

There is exactly one asyncio loop and one Gemini Live session per voice engine.
Stopping joins the voice thread before a new session may be created.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import subprocess
import struct
import time
import threading
import logging
from typing import Optional

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None

INPUT_RATE = 16000
OUTPUT_RATE = 24000
CHUNK_BYTES = 640 * 2  # 16-bit mono, 640 samples
WAKE_WORD = "hey axon"
LOG = logging.getLogger(__name__)
VOICE_LANGUAGES = ("en", "sw")


@contextlib.contextmanager
def _silence_native_stderr():
    try:
        fd = os.dup(2)
        with open(os.devnull, "w") as devnull:
            os.dup2(devnull.fileno(), 2)
        try:
            yield
        finally:
            os.dup2(fd, 2)
            os.close(fd)
    except Exception:
        yield


class GeminiLiveVoice:
    def __init__(self, api_key, on_transcript, on_state,
                 model="gemini-3.1-flash-live-preview", voice="Charon",
                 audio_source=None, on_audio_level=None):
        self.api_key = (api_key or "").strip()
        self.on_transcript = on_transcript
        self.on_state = on_state
        self.model = model
        self.voice = voice
        self.audio_source = (audio_source or os.environ.get("AXON_AUDIO_SOURCE", "")).strip() or None
        self.on_audio_level = on_audio_level
        self.audio_backend = "unknown"
        self.speaker_backend = "unknown"
        self.input_rms = 0.0
        self.input_peak = 0.0
        self.last_audio_signal = 0.0
        self.last_mic_error = ""

        self.running = False
        self._stopping = False
        self.thread: Optional[threading.Thread] = None
        self.loop = None
        self._stop_event: Optional[asyncio.Event] = None
        self._mic = None
        self._speaker = None
        self._speaker_lock = threading.RLock()
        self._session = None
        self._client = None
        self._greeting = False
        self._state_lock = threading.RLock()
        self._reconnect_event = threading.Event()
        self.reconnect_attempts = 0
        self.last_input_transcript = ""
        self.last_input_language = ""
        self.last_output_transcript = ""
        self.last_error = ""
        self.audio_chunks_sent = 0
        self._input_transcript_buffer = ""
        self._speech_detected = False
        self._last_speech_at = 0.0
        self.on_input_partial = None
        self.on_input_error = None
        self._tts_active = False
        self._tts_request_inflight = False
        self._tts_response_started = False
        self._tts_request_at = 0.0
        self._pending_tts_texts = []
        self._tts_lock = threading.RLock()
        self._session_resumption_handle = ""
        self._last_final_transcript = ""
        self._last_final_at = 0.0
        self.duplicate_turns_ignored = 0
        self.capture_suppressed_for_tts = 0
        self._capture_gate_logged = False
        self._aec_enabled = False
        self._aec_module_id = None
        self._aec_owned_module = False
        self._aec_source = None
        self._aec_sink = None
        self._last_spoken_fingerprint = ""
        self._last_spoken_at = 0.0

    @property
    def available(self):
        input_ready = bool(shutil.which("parec") or shutil.which("arecord"))
        output_ready = bool(shutil.which("paplay") or shutil.which("aplay"))
        return bool(self.api_key and genai and input_ready and output_ready)

    @property
    def microphone_ready(self):
        return bool(shutil.which("parec") or shutil.which("arecord"))

    def _detect_default_source(self):
        if self.audio_source:
            return self.audio_source
        pactl = shutil.which("pactl")
        if pactl:
            try:
                result = subprocess.run([pactl, "get-default-source"], capture_output=True, text=True, timeout=2, check=False)
                value = (result.stdout or "").strip()
                if value:
                    return value
            except Exception:
                pass
        return "system default"

    def audio_diagnostics(self):
        source = self._aec_source or self._detect_default_source()
        level = self.input_rms
        return {
            "backend": self.audio_backend,
            "speaker": self.speaker_backend,
            "source": source,
            "rms": level,
            "peak": self.input_peak,
            "chunks": self.audio_chunks_sent,
            "mic_error": self.last_mic_error,
            "last_error": self.last_error,
            "reconnect_attempts": self.reconnect_attempts,
            "duplicate_turns_ignored": self.duplicate_turns_ignored,
            "capture_suppressed_for_tts": self.capture_suppressed_for_tts,
            "aec_enabled": self._aec_enabled,
            "aec_source": self._aec_source or "",
            "aec_sink": self._aec_sink or "",
        }

    def start(self, greeting=False):
        with self._state_lock:
            if self.running:
                return True
            if not self.available:
                self.on_state("GEMINI NOT READY")
                return False
            # Never overlap an old voice thread with a new one.
            if self.thread and self.thread.is_alive():
                self.on_state("VOICE BUSY")
                return False
            self._greeting = bool(greeting)
            self._stopping = False
            self._reconnect_event.clear()
            self.reconnect_attempts = 0
            self.running = True
            self.thread = threading.Thread(
                target=self._thread_main,
                name="axon-gemini-voice",
                daemon=False,
            )
            self.thread.start()
            return True

    def stop(self, timeout=8.0):
        with self._state_lock:
            self._stopping = True
            self.running = False
            loop = self.loop
            event = self._stop_event
            self._reconnect_event.set()

        if loop and event and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(event.set)
            except Exception:
                pass

        t = self.thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=timeout)

        # Do not leave a stale thread reference that can be mistaken for a live session.
        with self._state_lock:
            if self.thread and not self.thread.is_alive():
                self.thread = None
        self.on_state("OFFLINE")

    def _thread_main(self):
        try:
            # A Live websocket can end after a network hiccup or service-side
            # session rotation. Do not convert one ended sender/receiver into a
            # permanently dead voice engine; rebuild the complete session.
            while self.running and not self._stopping:
                reason = "Live session ended unexpectedly"
                try:
                    # asyncio.run guarantees cancellation/shutdown per session.
                    asyncio.run(self._run())
                except Exception as exc:
                    reason = str(exc) or type(exc).__name__
                    self.last_error = reason
                    LOG.warning("Voice Live session ended: %s", reason)
                if not self.running or self._stopping:
                    break
                self.reconnect_attempts += 1
                delay = min(10.0, float(2 ** min(self.reconnect_attempts - 1, 3)))
                self.on_state(f"RECONNECTING ({int(delay)}s)")
                LOG.warning("Voice reconnect %d scheduled in %.0fs: %s", self.reconnect_attempts, delay, reason)
                if self._reconnect_event.wait(delay):
                    break
        finally:
            self._close_audio()
            with self._state_lock:
                self.running = False
                self._stopping = False
                self.loop = None
                self._stop_event = None
                self._session = None
                self._client = None

    async def _run(self):
        self.loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self.on_state("CONNECTING")

        client = None
        try:
            client = genai.Client(api_key=self.api_key)
            self._client = client

            config = {
                "response_modalities": ["AUDIO"],
                "input_audio_transcription": {},
                "output_audio_transcription": {},
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {"voice_name": self.voice}
                    }
                },
                "system_instruction": (
                    "You are AXON, a calm, natural, concise desktop AI assistant. "
                    "You are hands-free. Never narrate internal states. "
                    "The local AXON command router is authoritative for desktop actions. "
                    "Never claim an action happened unless AXON confirms it. "
                    "Do not answer user audio turns yourself: AXON's local command and "
                    "agent pipeline will send the verified response for you to speak. "
                    "Voice mode supports only English and Kiswahili (Swahili). "
                    "Transcribe those languages faithfully, preserve spoken names and "
                    "commands, and never transcribe or speak another language. "
                    "Speak in exactly one language per reply: match the user's English "
                    "or Kiswahili, and never repeat the answer as a bilingual translation."
                ),
                "thinking_config": {"thinking_level": "minimal"},
                # Ask the service for a resumable handle.  A later reconnect can
                # restore the Live conversation instead of creating an unrelated
                # session after a server rotation or network interruption.
                "session_resumption": (
                    {"handle": self._session_resumption_handle}
                    if self._session_resumption_handle else {}
                ),
                "realtime_input_config": {
                    # Continuous voice mode: microphone activity must not cut
                    # off AXON while it is speaking. The next completed turn is
                    # still transcribed and routed after the response finishes.
                    "activity_handling": "NO_INTERRUPTION",
                    "automatic_activity_detection": {
                        "disabled": False,
                        "prefix_padding_ms": 240,
                        # Faster than the former 850ms without cutting normal
                        # English/Kiswahili phrase endings.
                        "silence_duration_ms": 520,
                    }
                },
            }

            async with client.aio.live.connect(
                model=self.model, config=config
            ) as session:
                self._session = session
                self._open_audio()
                self.on_state("LISTENING")
                await self._drain_tts_queue()

                # Do not seed a spoken greeting.  A greeting was previously sent
                # as a Live text turn and could mask a missing user transcript.
                self._greeting = False

                sender = asyncio.create_task(
                    self._send_audio(session), name="axon-audio-sender"
                )
                receiver = asyncio.create_task(
                    self._receive_audio(session), name="axon-gemini-receiver"
                )
                stopper = asyncio.create_task(
                    self._stop_event.wait(), name="axon-voice-stop"
                )

                done, pending = await asyncio.wait(
                    {sender, receiver, stopper},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Always cancel and await the other tasks before leaving the
                # Live context. This is critical for google-genai cleanup.
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

                for task in done:
                    if task is not stopper:
                        if task.cancelled():
                            raise RuntimeError(f"{task.get_name()} was cancelled unexpectedly")
                        exc = task.exception()
                        if exc:
                            raise exc
                        # A receive iterator ending cleanly still means the Live
                        # session is gone; make the supervisor reconnect it.
                        raise RuntimeError(f"{task.get_name()} closed")

        finally:
            self._session = None
            # The Live context has already exited here. Close the client only after
            # every child task has been awaited.
            if client is not None:
                try:
                    aio = getattr(client, "aio", None)
                    close = getattr(aio, "aclose", None)
                    if close:
                        result = close()
                        if asyncio.iscoroutine(result):
                            await result
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Cleanup errors are reported but never tear down the process.
                    self.on_state(f"GEMINI CLEANUP: {str(exc)[:120]}")
            self._close_audio()

    def _pactl(self, *args, timeout=3):
        pactl = shutil.which("pactl")
        if not pactl:
            return None
        try:
            return subprocess.run([pactl, *args], capture_output=True, text=True, timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError):
            return None

    def _setup_echo_cancellation(self):
        """Create/reuse a PipeWire/PulseAudio WebRTC AEC pair.

        This is the primary echo fix. The virtual sink receives AXON TTS and
        the paired source applies acoustic echo cancellation against that
        playback reference before audio reaches Gemini STT. The old TTS gate
        remains as a safety net, so AEC failure never creates a self-chat loop.
        """
        self._aec_enabled = False
        self._aec_module_id = None
        self._aec_owned_module = False
        self._aec_source = None
        self._aec_sink = None
        pactl = shutil.which("pactl")
        if not pactl:
            return False

        source_name = "axon_echo_source"
        sink_name = "axon_echo_sink"
        modules = self._pactl("list", "short", "modules")
        existing_id = None
        if modules and modules.returncode == 0:
            for line in (modules.stdout or "").splitlines():
                parts = line.split(None, 2)
                if len(parts) >= 3 and "module-echo-cancel" in parts[1] and source_name in parts[2] and sink_name in parts[2]:
                    existing_id = parts[0]
                    break

        if existing_id:
            module_id = existing_id
            owned = False
        else:
            result = self._pactl(
                "load-module", "module-echo-cancel",
                f"source_name={source_name}",
                f"sink_name={sink_name}",
                "aec_method=webrtc",
                "use_master_format=1",
                timeout=5,
            )
            if not result or result.returncode != 0 or not (result.stdout or "").strip():
                LOG.warning("PipeWire/PulseAudio WebRTC echo cancellation is unavailable: %s", (result.stderr or "").strip())
                return False
            module_id = (result.stdout or "").strip().splitlines()[0].strip()
            owned = True

        # Give PipeWire/Pulse a moment to publish the virtual nodes.
        time.sleep(0.15)
        sources = self._pactl("list", "short", "sources")
        sinks = self._pactl("list", "short", "sinks")
        source_ok = bool(sources and source_name in (sources.stdout or ""))
        sink_ok = bool(sinks and sink_name in (sinks.stdout or ""))
        if not (source_ok and sink_ok):
            if owned and module_id:
                self._pactl("unload-module", str(module_id))
            LOG.warning("Echo-cancel module loaded but its virtual audio nodes were not published")
            return False

        self._aec_enabled = True
        self._aec_module_id = module_id
        self._aec_owned_module = owned
        self._aec_source = source_name
        self._aec_sink = sink_name
        LOG.info("Voice WebRTC AEC enabled: source=%s sink=%s module=%s", source_name, sink_name, module_id)
        return True

    def _teardown_echo_cancellation(self):
        module_id = self._aec_module_id
        owned = self._aec_owned_module
        self._aec_enabled = False
        self._aec_module_id = None
        self._aec_owned_module = False
        self._aec_source = None
        self._aec_sink = None
        if owned and module_id:
            self._pactl("unload-module", str(module_id), timeout=3)

    def _open_audio(self):
        self._close_audio()
        self.last_mic_error = ""

        # Prefer PipeWire/PulseAudio on Kali desktops.  The previous release
        # always opened ALSA's default device, which can be a different source
        # from the microphone selected by the desktop.  Keep ALSA as a safe
        # fallback for minimal/headless installations.
        pulse_input = shutil.which("parec")
        pulse_output = shutil.which("paplay")
        if pulse_input and pulse_output:
            self._setup_echo_cancellation()
        source = self._aec_source or self.audio_source
        if pulse_input:
            cmd = [pulse_input, "--raw", "--format=s16le", "--rate", str(INPUT_RATE), "--channels", "1"]
            if source:
                cmd += ["--device", source]
            try:
                self._mic = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
                time.sleep(0.12)
                if self._mic.poll() is not None:
                    err = self._mic.stderr.read().decode(errors="ignore").strip() if self._mic.stderr else ""
                    raise RuntimeError(err or "PipeWire/PulseAudio microphone process exited")
                self.audio_backend = "PipeWire/PulseAudio"
            except Exception as exc:
                self.last_mic_error = str(exc)[:180]
                self._close_audio()

        if self._mic is None and shutil.which("arecord"):
            try:
                cmd = ["arecord", "-q", "-t", "raw", "-f", "S16_LE", "-c", "1", "-r", str(INPUT_RATE), "-B", "200000", "-F", "40000"]
                self._mic = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
                time.sleep(0.12)
                if self._mic.poll() is not None:
                    err = self._mic.stderr.read().decode(errors="ignore").strip() if self._mic.stderr else ""
                    raise RuntimeError(err or "ALSA microphone process exited")
                self.audio_backend = "ALSA"
            except Exception as exc:
                self.last_mic_error = str(exc)[:180]
                self._close_audio()
                raise RuntimeError(f"Microphone could not be opened: {self.last_mic_error}")

        self._open_speaker(prefer_pulse=bool(pulse_output))

        if self._mic is None:
            raise RuntimeError("No microphone backend is available. Install/enable PipeWire-Pulse or ALSA capture tools.")
        if self._speaker is None:
            raise RuntimeError("No speaker playback backend is available. Install/enable paplay or aplay.")

    def _open_speaker(self, prefer_pulse=None):
        """Open playback using the established desktop audio backend.

        Reusing the original backend is essential after barge-in: switching a
        PipeWire session to ALSA mid-conversation can leave audio routed to a
        different device or make the next write fail.
        """
        if prefer_pulse is None:
            prefer_pulse = self.speaker_backend == "PipeWire/PulseAudio"
        candidates = []
        paplay = shutil.which("paplay")
        aplay = shutil.which("aplay")
        if prefer_pulse and paplay:
            command = [paplay, "--raw", "--format=s16le", "--rate", str(OUTPUT_RATE), "--channels", "1"]
            if self._aec_sink:
                command += ["--device", self._aec_sink]
            candidates.append(("PipeWire/PulseAudio", command))
        if aplay:
            candidates.append(("ALSA", [aplay, "-q", "-t", "raw", "-f", "S16_LE", "-c", "1", "-r", str(OUTPUT_RATE)]))
        if not prefer_pulse and paplay:
            command = [paplay, "--raw", "--format=s16le", "--rate", str(OUTPUT_RATE), "--channels", "1"]
            if self._aec_sink:
                command += ["--device", self._aec_sink]
            candidates.append(("PipeWire/PulseAudio", command))
        for backend, command in candidates:
            try:
                speaker = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, bufsize=0)
                with self._speaker_lock:
                    self._speaker = speaker
                    self.speaker_backend = backend
                LOG.info("Voice speaker opened with %s", backend)
                return True
            except OSError as exc:
                self.last_error = f"Speaker startup failed ({backend}): {exc}"
                LOG.warning("%s", self.last_error)
        with self._speaker_lock:
            self._speaker = None
        return False

    def _close_audio(self):
        mic, speaker = self._mic, self._speaker
        self._mic = self._speaker = None

        if mic:
            try:
                if mic.poll() is None:
                    mic.terminate()
                    mic.wait(timeout=1.5)
            except Exception:
                try:
                    mic.kill()
                except Exception:
                    pass

        if speaker:
            try:
                if speaker.stdin:
                    speaker.stdin.close()
            except Exception:
                pass
            try:
                if speaker.poll() is None:
                    speaker.terminate()
                    speaker.wait(timeout=1.5)
            except Exception:
                try:
                    speaker.kill()
                except Exception:
                    pass

        self._teardown_echo_cancellation()

    @staticmethod
    def _clean_text(text):
        return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9\s,'!?-]", " ", text or "")).strip()

    @staticmethod
    def _fingerprint_text(text):
        return re.sub(r"\W+", " ", str(text or "").lower()).strip()

    def _is_recent_output_echo(self, text):
        fingerprint = self._fingerprint_text(text)
        if not fingerprint or not self._last_spoken_fingerprint:
            return False
        age = time.monotonic() - self._last_spoken_at
        if age > 12.0:
            return False
        return fingerprint == self._last_spoken_fingerprint or (
            len(fingerprint) >= 18 and (fingerprint in self._last_spoken_fingerprint or self._last_spoken_fingerprint in fingerprint)
        )

    def _tts_capture_gated(self):
        return self._tts_active or (
            self._tts_request_inflight and time.monotonic() - self._tts_request_at < 45.0
        )

    async def _send_audio(self, session):
        while self.running and not self._stop_event.is_set():
            if not self._mic or not self._mic.stdout:
                raise RuntimeError("Microphone process is unavailable")
            chunk = await asyncio.to_thread(self._mic.stdout.read, CHUNK_BYTES)
            if not chunk:
                if self.running:
                    raise RuntimeError("Microphone stream ended")
                break
            # Measure the real microphone signal before sending it.  This makes
            # silent/wrong-input-device failures visible instead of reporting
            # only that PCM chunks were technically read.
            samples = struct.unpack("<%dh" % (len(chunk) // 2), chunk[:(len(chunk)//2)*2])
            if samples:
                sq = sum(x * x for x in samples) / len(samples)
                self.input_rms = min(1.0, (sq ** 0.5) / 32768.0)
                self.input_peak = min(1.0, max(abs(x) for x in samples) / 32768.0)
                self.last_audio_signal = time.time()
                LOG.debug("Voice microphone frame received: %d bytes rms=%.4f peak=%.4f", len(chunk), self.input_rms, self.input_peak)
                if self.input_rms >= 0.008:
                    if not self._speech_detected:
                        LOG.info("Voice speech detected: rms=%.4f peak=%.4f", self.input_rms, self.input_peak)
                    self._speech_detected = True
                    self._last_speech_at = time.time()
                cb = self.on_audio_level
                if cb and self.audio_chunks_sent % 4 == 0:
                    try:
                        cb(self.input_rms, self.input_peak)
                    except Exception:
                        pass
            if types is None:
                raise RuntimeError("google-genai types are unavailable")
            # Without hardware echo cancellation, sending AXON's speaker audio
            # back to Live creates a self-conversation loop. Keep reading the
            # microphone (so native capture stays healthy and the meter works),
            # but do not stream it while verified TTS is playing or queued.
            # Gate immediately when a verified reply is queued, not merely
            # after the first speaker packet arrives. This closes the small
            # window that allowed the beginning of AXON's own reply back into
            # microphone/STT. A timeout prevents a failed Live response from
            # silencing input forever.
            if self._tts_capture_gated():
                self.capture_suppressed_for_tts += 1
                if not self._capture_gate_logged:
                    LOG.info("Voice microphone streaming paused during TTS to prevent acoustic feedback")
                    self._capture_gate_logged = True
                continue
            self._capture_gate_logged = False
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={INPUT_RATE}")
            )
            self.audio_chunks_sent += 1

    async def _receive_audio(self, session):
        # google-genai's `receive()` iterator ends at every `turn_complete`.
        # Keep requesting the next iterator on the same websocket; ending this
        # coroutine here was the root cause of needless reconnect/TTS failures.
        while self.running and not self._stop_event.is_set():
            received = False
            async for response in session.receive():
                received = True
                if not self.running or self._stop_event.is_set():
                    return

                go_away = getattr(response, "go_away", None)
                if go_away is not None:
                    time_left = getattr(go_away, "time_left", None) or "soon"
                    self.last_error = f"Gemini Live requested session rotation (time left: {time_left})."
                    LOG.info("%s", self.last_error)
                    self.on_state("SESSION ROTATING")
                update = getattr(response, "session_resumption_update", None)
                if update is not None:
                    handle = str(getattr(update, "new_handle", "") or "")
                    resumable = getattr(update, "resumable", False)
                    if resumable and handle:
                        self._session_resumption_handle = handle
                        LOG.debug("Voice session resumption handle updated")
                    elif resumable is False:
                        self._session_resumption_handle = ""

                content = getattr(response, "server_content", None)
                if content is None:
                    continue
                if getattr(content, "interrupted", False):
                    LOG.info("Voice interruption flag received; keeping continuous playback")
                    continue

                inp = getattr(content, "input_transcription", None)
                if inp and getattr(inp, "text", None):
                    # Ignore stale/in-flight recognition while AXON owns the
                    # speaker. This keeps output echo out of HEARING/YOU and
                    # prevents it reaching the router.
                    if self._tts_capture_gated():
                        LOG.debug("Discarded input transcription during AXON TTS")
                        continue
                    language = str(getattr(inp, "language_code", getattr(inp, "languageCode", "")) or "").lower()
                    if language and not self._voice_language_supported(language):
                        self._reject_unsupported_language(language)
                        continue
                    if language:
                        self.last_input_language = language
                    text = self._clean_text(inp.text)
                    if text and self._is_recent_output_echo(text):
                        self.duplicate_turns_ignored += 1
                        LOG.warning("Discarded recent TTS echo transcript: %s", text)
                        continue
                    if text:
                        self._append_input_transcript(text)
                        self.on_state("UNDERSTANDING")

                if getattr(content, "turn_complete", False):
                    self._finalize_input_turn()
                    if self._tts_active:
                        LOG.info("Voice TTS completed")
                        self._tts_active = False
                    # A completed TTS turn must always release the capture gate,
                    # even when Gemini returned no audio packet. The previous
                    # response_started condition could leave STT muted until
                    # the 45-second timeout after a silent/partial response.
                    if self._tts_request_inflight:
                        self._tts_request_inflight = False
                        self._tts_response_started = False
                        self._tts_request_at = 0.0
                        asyncio.create_task(self._drain_tts_queue())

                out = getattr(content, "output_transcription", None)
                if out and getattr(out, "text", None):
                    text = self._clean_text(out.text)
                    if text:
                        self.last_output_transcript = text
                        self._last_spoken_fingerprint = self._fingerprint_text(text)
                        self._last_spoken_at = time.monotonic()
                        callback = getattr(self, "on_output_transcript", None)
                        if callback:
                            callback(text)

                model_turn = getattr(content, "model_turn", None)
                if model_turn:
                    # Live may try to answer the microphone turn itself. AXON
                    # is authoritative: discard that unsolicited audio. Only a
                    # response explicitly queued by _deliver_voice_response is
                    # allowed to reach the speaker.
                    if not self._tts_request_inflight:
                        LOG.warning("Discarded unsolicited Gemini Live audio; awaiting AXON router response")
                        continue
                    self._tts_response_started = True
                    self.on_state("SPEAKING")
                    spoke = False
                    for part in model_turn.parts:
                        inline = getattr(part, "inline_data", None)
                        data = getattr(inline, "data", None) if inline else None
                        if data:
                            if not spoke:
                                if not self._tts_active:
                                    LOG.info("Voice TTS started")
                                    self._tts_active = True
                                spoke = True
                            await asyncio.to_thread(self._write_speaker, data)
                    self.on_state("LISTENING")
            # An empty iterator means the websocket really closed. Let the
            # supervisor reconnect; a normal completed turn has messages.
            if not received:
                return

    def _append_input_transcript(self, text):
        """Merge either cumulative or delta Live transcription fragments."""
        current = self._input_transcript_buffer
        if text == current or (current and current.endswith(text)):
            return
        if current and text.startswith(current):
            merged = text
        elif current and current.startswith(text):
            merged = current
        else:
            merged = (current + " " + text).strip()
        self._input_transcript_buffer = merged
        self.last_input_transcript = merged
        LOG.info("Voice partial transcript: %s", merged)
        if self.on_input_partial:
            self.on_input_partial(merged)

    @staticmethod
    def _voice_language_supported(language):
        return any(language == code or language.startswith(code + "-") for code in VOICE_LANGUAGES)

    def _reject_unsupported_language(self, language):
        self._input_transcript_buffer = ""
        self._speech_detected = False
        message = f"Voice supports English and Kiswahili only; Gemini Live reported unsupported input language '{language}'."
        self.last_error = message
        LOG.warning("%s", message)
        if self.on_input_error:
            self.on_input_error(message)
        self.on_state("LISTENING")

    def _finalize_input_turn(self):
        text = self._input_transcript_buffer.strip()
        self._input_transcript_buffer = ""
        heard_speech = self._speech_detected
        self._speech_detected = False
        if text:
            normalized = re.sub(r"\W+", " ", text.lower()).strip()
            now = time.monotonic()
            if normalized and normalized == self._last_final_transcript and now - self._last_final_at < 3.0:
                self.duplicate_turns_ignored += 1
                LOG.warning("Voice duplicate final transcript ignored: %s", text)
                return
            self._last_final_transcript = normalized
            self._last_final_at = now
            self.last_input_transcript = text
            LOG.info("Voice final transcript: %s", text)
            self.on_transcript(text)
        elif heard_speech:
            # Gemini can emit speech-activity events without an input transcript.
            # This is common when the microphone hears music, browser audio,
            # short noises, or an AEC residual. It is not a fatal voice-engine
            # error and must never force a reconnect/error loop. Keep listening
            # and let the next complete turn provide the transcript.
            LOG.debug("Gemini Live reported speech activity but returned no input transcript; continuing to listen")

    def set_input_transcript_callbacks(self, on_partial=None, on_error=None):
        self.on_input_partial = on_partial
        self.on_input_error = on_error

    def set_output_transcript_callback(self, callback):
        self.on_output_transcript = callback

    async def _send_text_async(self, text):
        await self._drain_tts_queue()
        return True

    async def _drain_tts_queue(self):
        """Speak verified AXON replies serially, never over an active reply."""
        if self._tts_request_inflight:
            return
        if not self._session or not self.running:
            return
        with self._tts_lock:
            if not self._pending_tts_texts:
                return
        text = self._pending_tts_texts.pop(0)
        self._tts_request_inflight = True
        self._tts_response_started = False
        self._tts_request_at = time.monotonic()
        try:
            await self._session.send_realtime_input(text=text)
        except Exception:
            self._tts_request_inflight = False
            with self._tts_lock:
                self._pending_tts_texts.insert(0, text)
            raise

    def send_text(self, text):
        """Queue a governed AXON result and recover a dead Live session.

        A verified local command must never fail merely because the Live
        websocket is between reconnects. The response is persisted in the
        in-memory TTS queue and the voice supervisor is restarted when it has
        unexpectedly stopped. The next healthy Live session drains the queue.
        """
        text = str(text or "").strip()
        if not text or self._stopping:
            return False

        with self._tts_lock:
            self._pending_tts_texts.append(text)

        # A Live disconnect can finish the supervisor thread and set running
        # false. Previously this made _deliver_voice_response throw
        # ``Gemini Live TTS session is unavailable`` and the verified command
        # result was lost. Restart the voice supervisor so the durable queue is
        # drained automatically.
        if not self.running:
            with self._state_lock:
                if not self.running and not self._stopping and self.available:
                    self._reconnect_event.clear()
                    self.reconnect_attempts = 0
                    self.running = True
                    self.thread = threading.Thread(
                        target=self._thread_main,
                        name="axon-gemini-voice-recovery",
                        daemon=False,
                    )
                    self.thread.start()
            return True

        loop = self.loop
        if not loop or loop.is_closed():
            # The reconnect supervisor will drain this durable queue as soon as
            # the next Live session is connected.
            return True
        try:
            asyncio.run_coroutine_threadsafe(self._send_text_async(text), loop)
            return True
        except Exception as exc:
            self.last_error = str(exc)
            # Preserve the queued response for the next connected session.
            return True

    def _write_speaker(self, data):
        try:
            with self._speaker_lock:
                speaker = self._speaker
                if not speaker or speaker.poll() is not None or not speaker.stdin:
                    raise BrokenPipeError("speaker process is unavailable")
                speaker.stdin.write(data)
                speaker.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            # Playback loss must not terminate the receiver coroutine and take
            # down STT. Recreate the same backend; the next Live audio chunk
            # resumes normally.
            self.last_error = f"Speaker write failed: {exc}"
            LOG.warning("%s; recovering speaker", self.last_error)
            if self.running and not self._stopping:
                self._clear_speaker()

    def _clear_speaker(self):
        # Immediately clear stale output after a Gemini interruption, then
        # restore the same backend selected at session startup.
        with self._speaker_lock:
            old = self._speaker
            self._speaker = None
        if old:
            try:
                if old.stdin:
                    old.stdin.close()
                old.terminate()
                old.wait(timeout=1)
            except Exception:
                try:
                    old.kill()
                except Exception:
                    pass
        if self.running and not self._stopping:
            with _silence_native_stderr():
                if not self._open_speaker():
                    LOG.error("Voice speaker recovery failed; STT remains active")
