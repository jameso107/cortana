"""
Voice pipeline: mic → VAD → keyword spotting → STT → orchestrator → TTS.

Wake word detection uses a two-stage approach:
  1. Silero VAD detects speech segments (very lightweight, <1% CPU)
  2. faster-whisper tiny.en transcribes the segment and checks for "hey cortana"
     (much more accurate than trying to train a custom OWW model)

STT for full utterances uses faster-whisper medium.en for quality.
TTS uses Kokoro af_sky (American female).
"""
from __future__ import annotations

import asyncio
import logging
import os
import queue
import time

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE     = 16000
CHUNK           = 512           # VAD chunk size (32ms)
WAKE_PHRASES    = {"hey cortana", "hey, cortana", "a cortana", "hey cortana,"}
SILENCE_THRESH  = 0.015
SILENCE_SEC     = 1.2
MAX_RECORD_SEC  = 30
PRE_BUFFER_SEC  = 0.5          # audio to keep before wake word is detected


class VoicePipeline:
    def __init__(self, orchestrator):
        from cortana.config import get_config
        self.cfg          = get_config().voice
        self.orchestrator = orchestrator
        self._running     = False
        self._speaking    = False
        self._vad         = None   # Silero VAD
        self._tiny        = None   # whisper tiny.en (wake word check)
        self._whisper     = None   # whisper medium.en (full STT)
        self._kokoro      = None
        self._loop        = None

    # ── Startup ───────────────────────────────────────────────────────────────

    async def start(self):
        self._loop = asyncio.get_event_loop()
        log.info("Loading voice models…")
        await asyncio.gather(
            asyncio.to_thread(self._load_vad),
            asyncio.to_thread(self._load_whisper),
            asyncio.to_thread(self._load_tts),
        )
        self._running = True
        log.info("Voice pipeline ready — say 'Hey Cortana'")
        await asyncio.to_thread(self._listen_loop)

    def _load_vad(self):
        import torch
        torch.hub.set_dir(os.path.expanduser("~/.cortana/models/torch_hub"))
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            trust_repo=True,
            onnx=True,
        )
        self._vad = model
        self._vad_utils = utils
        log.info("Silero VAD loaded.")

        # Load tiny whisper for wake word detection
        from faster_whisper import WhisperModel
        self._tiny = WhisperModel("tiny.en", device="cpu", compute_type="int8")
        log.info("Whisper tiny.en loaded for wake word detection.")

    def _load_whisper(self):
        from faster_whisper import WhisperModel
        self._whisper = WhisperModel("medium.en", device="cpu", compute_type="int8")
        log.info("Whisper medium.en loaded for STT.")

    def _load_tts(self):
        tts_dir = os.path.expanduser("~/.cortana/models/tts")
        onnx    = f"{tts_dir}/kokoro-v1.0.onnx"
        voices  = f"{tts_dir}/voices-v1.0.bin"
        if not os.path.exists(onnx):
            log.warning("Kokoro model not found — using macOS say.")
            return
        try:
            from kokoro_onnx import Kokoro
            self._kokoro = Kokoro(onnx, voices)
            log.info("Kokoro TTS loaded (voice: %s).", self.cfg.tts_voice)
        except Exception as exc:
            log.warning("Kokoro failed (%s) — using macOS say.", exc)

    # ── Listen loop ───────────────────────────────────────────────────────────

    def _listen_loop(self):
        audio_q: queue.Queue[np.ndarray] = queue.Queue()
        pre_buffer: list[np.ndarray] = []     # rolling window before wake word
        pre_max = int(PRE_BUFFER_SEC * SAMPLE_RATE / CHUNK)

        def mic_cb(indata, frames, t, status):
            if not self._speaking:
                audio_q.put(indata[:, 0].copy())

        log.info("Mic open — listening for 'Hey Cortana'")
        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=CHUNK, callback=mic_cb,
        ):
            speech_frames: list[np.ndarray] = []
            in_speech = False
            silence_count = 0
            silence_needed = int(0.5 * SAMPLE_RATE / CHUNK)

            while self._running:
                try:
                    chunk = audio_q.get(timeout=1.0)
                except queue.Empty:
                    continue

                # VAD
                import torch
                t_chunk = torch.from_numpy(chunk)
                speech_prob = float(self._vad(t_chunk, SAMPLE_RATE).item())

                if speech_prob > 0.5:
                    if not in_speech:
                        in_speech = True
                        speech_frames = list(pre_buffer)  # include pre-buffer
                    speech_frames.append(chunk)
                    silence_count = 0
                else:
                    if in_speech:
                        silence_count += 1
                        speech_frames.append(chunk)
                        if silence_count >= silence_needed:
                            # End of speech — check for wake word
                            segment = np.concatenate(speech_frames)
                            in_speech = False
                            speech_frames = []
                            silence_count = 0
                            if self._is_wake_word(segment):
                                log.info("Wake word detected!")
                                utterance = self._record_utterance(audio_q)
                                if utterance is not None:
                                    asyncio.run_coroutine_threadsafe(
                                        self._handle_utterance(utterance), self._loop
                                    )

                # Maintain pre-buffer
                pre_buffer.append(chunk)
                if len(pre_buffer) > pre_max:
                    pre_buffer.pop(0)

    def _is_wake_word(self, audio: np.ndarray) -> bool:
        """Check if audio contains 'hey cortana' using tiny whisper."""
        try:
            segs, _ = self._tiny.transcribe(audio, beam_size=1, language="en",
                                             vad_filter=False)
            text = " ".join(s.text for s in segs).strip().lower()
            log.debug("Wake word check: '%s'", text)
            return any(phrase in text for phrase in WAKE_PHRASES)
        except Exception as exc:
            log.debug("Wake word check error: %s", exc)
            return False

    def _record_utterance(self, audio_q: queue.Queue) -> np.ndarray | None:
        """Record until silence after wake word."""
        log.info("Listening for command…")
        frames: list[np.ndarray] = []
        silent_chunks = 0
        max_chunks    = int(MAX_RECORD_SEC * SAMPLE_RATE / CHUNK)
        sil_needed    = int(SILENCE_SEC * SAMPLE_RATE / CHUNK)

        while len(frames) < max_chunks:
            try:
                chunk = audio_q.get(timeout=2.0)
            except queue.Empty:
                break
            frames.append(chunk)
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            if rms < SILENCE_THRESH:
                silent_chunks += 1
                if silent_chunks >= sil_needed and len(frames) > 8:
                    break
            else:
                silent_chunks = 0

        return np.concatenate(frames) if frames else None

    # ── Dispatch + TTS ────────────────────────────────────────────────────────

    async def _handle_utterance(self, audio: np.ndarray):
        text = await asyncio.to_thread(self._transcribe, audio)
        text = text.strip()
        if not text:
            return
        log.info("Command: %s", text)
        from cortana.core.orchestrator import Request
        response = await self.orchestrator.handle(Request(text=text, source="voice"))
        if response.text:
            await self.speak(response.text)

    def _transcribe(self, audio: np.ndarray) -> str:
        segs, _ = self._whisper.transcribe(audio, beam_size=5, language="en")
        return " ".join(s.text for s in segs).strip()

    async def speak(self, text: str):
        self._speaking = True
        try:
            await asyncio.to_thread(self._play_tts, text)
        finally:
            self._speaking = False

    def _play_tts(self, text: str):
        if self._kokoro is not None:
            try:
                samples, sr = self._kokoro.create(
                    text, voice=self.cfg.tts_voice, speed=1.0, lang="en-us"
                )
                sd.play(samples, sr, blocking=True)
                return
            except Exception as exc:
                log.warning("Kokoro TTS error: %s — falling back.", exc)
        import subprocess
        subprocess.run(["say", "-v", "Samantha", text])

    async def stop(self):
        self._running = False
