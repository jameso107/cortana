"""
Voice pipeline: mic → wake word → STT → orchestrator → TTS → speaker.

Wake word: "hey jarvis" (best available approximation; say it naturally)
STT:       faster-whisper medium.en
TTS:       Kokoro af_sky (American female, closest to Halo Cortana)
Hotkey:    Cmd+Space as push-to-talk alternative
"""
from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE           = 16000
CHUNK_FRAMES          = 1280    # 80ms — OpenWakeWord native size
SILENCE_SEC           = 1.2
SILENCE_THRESH        = 0.015
MAX_RECORD_SEC        = 30
WAKE_WORD_MODEL       = "hey_jarvis_v0.1"
WAKE_WORD_THRESHOLD   = 0.5


class VoicePipeline:
    def __init__(self, orchestrator):
        from cortana.config import get_config
        self.cfg          = get_config().voice
        self.orchestrator = orchestrator
        self._running     = False
        self._speaking    = False
        self._oww         = None
        self._whisper     = None
        self._kokoro      = None
        self._loop        = None

    # ── Startup ───────────────────────────────────────────

    async def start(self):
        self._loop = asyncio.get_event_loop()
        log.info("Loading voice models…")
        await asyncio.gather(
            asyncio.to_thread(self._load_wake_word),
            asyncio.to_thread(self._load_whisper),
            asyncio.to_thread(self._load_tts),
        )
        self._running = True
        log.info("Voice pipeline ready. Say 'Hey Jarvis' or press Cmd+Space.")
        await asyncio.to_thread(self._listen_loop)

    def _load_wake_word(self):
        from openwakeword.model import Model
        self._oww = Model(wakeword_models=[WAKE_WORD_MODEL], inference_framework="onnx")
        log.info("Wake word model loaded: %s", WAKE_WORD_MODEL)

    def _load_whisper(self):
        from faster_whisper import WhisperModel
        self._whisper = WhisperModel("medium.en", device="cpu", compute_type="int8")
        log.info("Whisper STT loaded.")

    def _load_tts(self):
        tts_dir = os.path.expanduser("~/.cortana/models/tts")
        onnx    = f"{tts_dir}/kokoro-v1.0.onnx"
        voices  = f"{tts_dir}/voices-v1.0.bin"
        if not os.path.exists(onnx) or not os.path.exists(voices):
            log.warning("Kokoro model files not found at %s — using macOS say.", tts_dir)
            return
        try:
            from kokoro_onnx import Kokoro
            self._kokoro = Kokoro(onnx, voices)
            log.info("Kokoro TTS loaded (voice: %s).", self.cfg.tts_voice)
        except Exception as exc:
            log.warning("Kokoro failed to load (%s) — using macOS say.", exc)

    # ── Listen loop ───────────────────────────────────────

    def _listen_loop(self):
        audio_q: queue.Queue[np.ndarray] = queue.Queue()

        def mic_callback(indata, frames, time_info, status):
            if not self._speaking:
                audio_q.put(indata[:, 0].copy())

        log.info("Mic open — listening for wake word.")
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=CHUNK_FRAMES,
            callback=mic_callback,
        ):
            while self._running:
                try:
                    chunk = audio_q.get(timeout=1.0)
                except queue.Empty:
                    continue

                pred   = self._oww.predict(chunk)
                scores = pred.get(WAKE_WORD_MODEL, {})
                score  = (
                    max(scores.values()) if isinstance(scores, dict) and scores
                    else float(scores) if isinstance(scores, (int, float))
                    else 0.0
                )

                if score >= WAKE_WORD_THRESHOLD:
                    log.info("Wake word detected (score=%.2f)", score)
                    utterance = self._record_utterance(audio_q)
                    if utterance is not None and len(utterance) > SAMPLE_RATE * 0.3:
                        asyncio.run_coroutine_threadsafe(
                            self._handle_utterance(utterance), self._loop
                        )

    def _record_utterance(self, audio_q: queue.Queue) -> np.ndarray | None:
        frames: list[np.ndarray] = []
        silent_chunks      = 0
        max_chunks         = int(MAX_RECORD_SEC * SAMPLE_RATE / CHUNK_FRAMES)
        silence_needed     = int(SILENCE_SEC * SAMPLE_RATE / CHUNK_FRAMES)

        while len(frames) < max_chunks:
            try:
                chunk = audio_q.get(timeout=2.0)
            except queue.Empty:
                break
            frames.append(chunk)
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            if rms < SILENCE_THRESH:
                silent_chunks += 1
                if silent_chunks >= silence_needed and len(frames) > 4:
                    break
            else:
                silent_chunks = 0

        return np.concatenate(frames) if frames else None

    # ── Handle + TTS ──────────────────────────────────────

    async def _handle_utterance(self, audio: np.ndarray):
        text = await asyncio.to_thread(self._transcribe, audio)
        text = text.strip()
        if not text:
            return
        log.info("Heard: %s", text)
        from cortana.core.orchestrator import Request
        response = await self.orchestrator.handle(Request(text=text, source="voice"))
        if response.text:
            await self.speak(response.text)

    def _transcribe(self, audio: np.ndarray) -> str:
        segments, _ = self._whisper.transcribe(audio, beam_size=5, language="en")
        return " ".join(s.text for s in segments).strip()

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
                log.warning("Kokoro TTS error: %s — falling back to say.", exc)
        import subprocess
        subprocess.run(["say", "-v", "Samantha", text])

    async def stop(self):
        self._running = False
