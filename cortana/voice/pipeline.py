"""
Voice pipeline: mic → VAD → STT → orchestrator → TTS.

Activated by the UI toggle button (no wake word).
When voice_mode is enabled via WebSocket, the pipeline continuously
listens for speech, transcribes it, and responds.
"""
from __future__ import annotations

import asyncio
import logging
import os
import queue
import re

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE    = 16000
CHUNK          = 512          # 32ms per VAD chunk
MAX_RECORD_SEC = 30
MIN_SPEECH_SEC = 0.3          # ignore sub-300ms blips (coughs, transients)

# Sentence-boundary splitter for streaming TTS (speak each sentence as it lands).
_SENTENCE_RE = re.compile(r".+?[.!?…](?:\s|$)|.+?[\n]", re.S)


class VoicePipeline:
    def __init__(self, orchestrator):
        from cortana.config import get_config
        self.cfg          = get_config().voice
        self.orchestrator = orchestrator
        self._running     = False
        self._listening   = False   # voice mode on/off
        self._speaking    = False
        self._vad         = None
        self._whisper     = None
        self._kokoro      = None
        self._loop        = None
        self._audio_q: queue.Queue[np.ndarray] = queue.Queue()
        # Endpointing / VAD tuning, driven by config (previously hardcoded).
        self._silence_sec   = self.cfg.silence_ms / 1000.0
        self._vad_threshold = self.cfg.vad_threshold

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
        log.info("Voice pipeline ready — toggle via UI button.")
        await asyncio.to_thread(self._mic_loop)

    def _load_vad(self):
        import torch
        torch.hub.set_dir(os.path.expanduser("~/.cortana/models/torch_hub"))
        model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            trust_repo=True,
            onnx=True,
        )
        self._vad = model
        log.info("Silero VAD loaded.")

    def _load_whisper(self):
        from faster_whisper import WhisperModel
        model = self.cfg.stt_model or "medium.en"
        self._whisper = WhisperModel(model, device="cpu", compute_type="int8")
        log.info("Whisper %s loaded.", model)

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

    # ── Toggle ────────────────────────────────────────────────────────────────

    def set_listening(self, enabled: bool):
        self._listening = enabled
        log.info("Voice mode %s.", "ON" if enabled else "OFF")

    # ── Mic loop ──────────────────────────────────────────────────────────────

    def _mic_loop(self):
        """Keep mic open permanently; feed audio to queue only when listening."""
        def mic_cb(indata, frames, t, status):
            if self._listening and not self._speaking:
                self._audio_q.put(indata[:, 0].copy())

        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=CHUNK, callback=mic_cb,
        ):
            log.info("Mic open.")
            while self._running:
                if self._listening:
                    self._process_one_utterance()
                else:
                    # Drain any queued audio from before voice mode was off
                    while not self._audio_q.empty():
                        self._audio_q.get_nowait()
                    import time
                    time.sleep(0.1)

    def _process_one_utterance(self):
        """Record one utterance (VAD-gated) and dispatch it."""
        import torch

        # Silero VAD is a stateful RNN; clear hidden state so each utterance is
        # scored independently and the onset of a new one isn't clipped.
        if hasattr(self._vad, "reset_states"):
            self._vad.reset_states()

        speech_frames: list[np.ndarray] = []
        speech_chunks = 0
        in_speech     = False
        silence_count = 0
        sil_needed    = max(int(self._silence_sec * SAMPLE_RATE / CHUNK), 1)
        min_speech    = max(int(MIN_SPEECH_SEC * SAMPLE_RATE / CHUNK), 1)
        max_chunks    = int(MAX_RECORD_SEC * SAMPLE_RATE / CHUNK)

        while self._listening and len(speech_frames) < max_chunks:
            try:
                chunk = self._audio_q.get(timeout=0.5)
            except queue.Empty:
                # If we were in speech and timed out, treat as end
                if in_speech and silence_count > 0:
                    break
                continue

            t_chunk     = torch.from_numpy(chunk)
            speech_prob = float(self._vad(t_chunk, SAMPLE_RATE).item())

            if speech_prob > self._vad_threshold:
                in_speech = True
                speech_frames.append(chunk)
                speech_chunks += 1
                silence_count = 0
            elif in_speech:
                speech_frames.append(chunk)
                silence_count += 1
                if silence_count >= sil_needed:
                    break  # end of utterance

        # Require a minimum amount of actual speech so a cough/transient over the
        # VAD threshold doesn't trigger a full transcribe + turn on noise.
        if not in_speech or speech_chunks < min_speech:
            return

        # Trim the trailing silence tail (keep a small pad) before transcription
        # so whisper doesn't waste work and hallucinate trailing tokens.
        keep = max(len(speech_frames) - silence_count + 2, speech_chunks)
        audio = np.concatenate(speech_frames[:keep])
        asyncio.run_coroutine_threadsafe(
            self._handle_utterance(audio), self._loop
        )

    # ── Dispatch + TTS ────────────────────────────────────────────────────────

    async def _handle_utterance(self, audio: np.ndarray):
        text = await asyncio.to_thread(self._transcribe, audio)
        text = text.strip()
        if not text:
            return
        log.info("Heard: %s", text)

        from cortana.core.ws_server import broadcast
        from cortana.core.orchestrator import Request

        await broadcast({"type": "voice_input", "text": text})
        await broadcast({"type": "status", "value": "thinking"})

        # Stream the reply into sentence-chunked TTS so speech begins after the
        # first sentence, not after the whole answer is generated + synthesized.
        # A background player consumes sentences while generation continues.
        self._speaking = True  # gate the mic for the whole spoken reply
        speech_q: asyncio.Queue[str | None] = asyncio.Queue()
        player = asyncio.create_task(self._play_queue(speech_q))
        buf = ""
        spoke_streaming = False
        speaking_announced = False

        async def emit(ev: dict):
            nonlocal buf, spoke_streaming, speaking_announced
            etype = ev.get("type")
            # Forward stream events to any connected UI so voice replies stream there too.
            await broadcast(ev)
            if etype == "stream_delta":
                if not speaking_announced:
                    await broadcast({"type": "status", "value": "speaking"})
                    speaking_announced = True
                buf += ev.get("text", "")
                sentences, buf = self._split_sentences(buf)
                for s in sentences:
                    spoke_streaming = True
                    await speech_q.put(s)
            elif etype == "stream_cancel":
                buf = ""  # preamble before a tool call — not the spoken reply
            elif etype == "error":
                buf = ""  # transient failure — say nothing

        response = await self.orchestrator.handle(Request(text=text, source="voice"), emit=emit)

        # Flush any remaining buffered text; if nothing streamed (e.g. a fallback
        # reply), speak the final response text as a whole.
        tail = buf.strip()
        if tail:
            await speech_q.put(tail)
        elif not spoke_streaming and response.text:
            await broadcast({"type": "status", "value": "speaking"})
            await speech_q.put(response.text)

        await speech_q.put(None)   # sentinel: no more sentences
        await player               # wait for playback to finish
        self._speaking = False
        await broadcast({"type": "status", "value": "listening"})

    async def _play_queue(self, q: "asyncio.Queue[str | None]"):
        """Consume sentences and speak them in order; playback overlaps ongoing generation."""
        while True:
            item = await q.get()
            if item is None:
                break
            item = item.strip()
            if item:
                await asyncio.to_thread(self._play_tts, item)

    @staticmethod
    def _split_sentences(buf: str) -> tuple[list[str], str]:
        """Split off complete sentences from buf; return (sentences, remainder)."""
        sentences: list[str] = []
        pos = 0
        for m in _SENTENCE_RE.finditer(buf):
            sentences.append(m.group().strip())
            pos = m.end()
        return [s for s in sentences if s], buf[pos:]

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
