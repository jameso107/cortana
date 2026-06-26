"""Voice pipeline: wake word → STT → orchestrator → TTS."""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


class VoicePipeline:
    """
    Manages the always-on mic thread, wake word detection,
    transcription, and TTS output. Not yet fully implemented —
    stubs are in place for each stage.
    """

    def __init__(self, orchestrator):
        from cortana.config import get_config
        self.cfg = get_config().voice
        self.orchestrator = orchestrator
        self._running = False

    async def start(self):
        log.info("Voice pipeline starting (wake word: '%s')", self.cfg.wake_word)
        self._running = True
        await self._listen_loop()

    async def stop(self):
        self._running = False

    async def _listen_loop(self):
        """Main loop: detect wake word, transcribe, dispatch, speak."""
        log.info("Listening… (stub — full implementation pending)")
        # TODO: integrate openwakeword for wake word detection
        # TODO: integrate faster-whisper for STT
        # TODO: integrate Kokoro for TTS
        while self._running:
            await asyncio.sleep(1)

    async def speak(self, text: str):
        """TTS output — Kokoro with macOS fallback."""
        log.debug("TTS: %s", text[:80])
        # TODO: call Kokoro TTS
        # Fallback: macOS say command
        import subprocess
        subprocess.Popen(["say", text])

    async def transcribe(self, audio_bytes: bytes) -> str:
        """Run whisper.cpp on captured audio."""
        # TODO: call faster-whisper
        return ""
