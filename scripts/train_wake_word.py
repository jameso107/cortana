"""
Train a custom "hey cortana" wake word model.

Strategy: generate synthetic samples via Kokoro TTS, extract OpenWakeWord
embeddings, train a scikit-learn logistic regression classifier on top.
No heavy training deps (SpeechBrain etc.) required.

Usage:
  python scripts/train_wake_word.py
  python scripts/train_wake_word.py --record   # also record your own voice
"""
from __future__ import annotations

import argparse
import os
import queue
import struct
import tempfile
import time
from pathlib import Path

import joblib
import numpy as np
import sounddevice as sd
import soundfile as sf
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report

SAMPLE_RATE   = 16000
CHUNK         = 1280          # OWW native chunk size (80ms)
TTS_DIR       = Path.home() / ".cortana/models/tts"
OUT_DIR       = Path.home() / ".cortana/models"
SYNTH_DIR     = OUT_DIR / "ww_training"
MODEL_OUT     = OUT_DIR / "hey_cortana.joblib"

PHRASE        = "hey cortana"
NEGATIVE_PHRASES = [
    "what time is it", "open spotify", "search for news",
    "hey siri", "ok google", "alexa turn on lights",
    "set a timer for five minutes", "play some music",
    "call mom", "send a message", "cortana what is the weather",
    "how are you doing today", "tell me a joke",
]
TTS_VOICES    = ["af_sky", "af_bella", "af_sarah", "af_nova", "af_jessica"]
TTS_SPEEDS    = [0.85, 0.95, 1.0, 1.1, 1.25]


# ── Audio helpers ──────────────────────────────────────────────────────────────

def tts_to_array(kokoro, phrase: str, voice: str, speed: float) -> np.ndarray:
    samples, sr = kokoro.create(phrase, voice=voice, speed=speed, lang="en-us")
    if sr != SAMPLE_RATE:
        import torchaudio.functional as F
        import torch
        t = torch.tensor(samples).unsqueeze(0).float()
        samples = F.resample(t, sr, SAMPLE_RATE).squeeze(0).numpy()
    return samples.astype(np.float32)


def pad_or_trim(audio: np.ndarray, length: int) -> np.ndarray:
    if len(audio) >= length:
        return audio[:length]
    return np.pad(audio, (0, length - len(audio)))


# ── Embedding extraction ───────────────────────────────────────────────────────

def extract_embeddings(oww_model, audio: np.ndarray) -> np.ndarray:
    """Run audio through OWW's embedding model and return the feature vector."""
    n_chunks   = len(audio) // CHUNK
    embeddings = []
    for i in range(n_chunks):
        chunk = audio[i * CHUNK:(i + 1) * CHUNK]
        oww_model.predict(chunk)

    # Pull the latest embedding from the model's internal buffer
    emb = oww_model.preprocessor.get_embedding(audio)
    return emb.flatten()


def get_embeddings_batch(oww_model, clips: list[np.ndarray]) -> np.ndarray:
    """Extract a single representative embedding per clip using OWW's preprocessor."""
    results = []
    for audio in clips:
        # Feed chunks through to warm the preprocessor, collect final state
        oww_model.reset()
        chunks = [audio[i*CHUNK:(i+1)*CHUNK] for i in range(len(audio)//CHUNK)]
        for chunk in chunks:
            oww_model.predict(chunk)
        # Use the embedding buffer from the preprocessor
        buf = oww_model.preprocessor.get_embeddings()  # (N, 96)
        if buf is not None and len(buf) > 0:
            results.append(buf[-1])   # last frame embedding
        else:
            results.append(np.zeros(96))
    return np.array(results)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", action="store_true",
                        help="Record your own voice samples (improves accuracy)")
    args = parser.parse_args()

    SYNTH_DIR.mkdir(parents=True, exist_ok=True)

    # Load TTS
    print("Loading Kokoro TTS…")
    from kokoro_onnx import Kokoro
    kokoro = Kokoro(str(TTS_DIR / "kokoro-v1.0.onnx"), str(TTS_DIR / "voices-v1.0.bin"))

    # Load OWW (just for embeddings — we ignore its classifier)
    print("Loading OpenWakeWord embedding model…")
    from openwakeword.model import Model
    oww = Model(wakeword_models=["hey_jarvis_v0.1"], inference_framework="onnx")

    # ── Generate positive samples ──────────────────────────────────────────────
    print(f"\nGenerating positive samples for '{PHRASE}'…")
    pos_clips: list[np.ndarray] = []
    idx = 0
    for voice in TTS_VOICES:
        for speed in TTS_SPEEDS:
            for noise_level in [0.0, 0.002, 0.005]:
                audio = tts_to_array(kokoro, PHRASE, voice, speed)
                if noise_level > 0:
                    audio = np.clip(audio + np.random.randn(len(audio)) * noise_level, -1, 1)
                pos_clips.append(audio)
                idx += 1
    print(f"  {len(pos_clips)} positive clips generated.")

    if args.record:
        print(f"\nRecord your own voice saying '{PHRASE}'.")
        real = record_samples(PHRASE, n=25)
        pos_clips.extend(real)
        print(f"  Total positive clips: {len(pos_clips)}")

    # ── Generate negative samples ──────────────────────────────────────────────
    print("\nGenerating negative samples…")
    neg_clips: list[np.ndarray] = []
    for phrase in NEGATIVE_PHRASES:
        for voice in TTS_VOICES[:2]:
            for speed in [0.9, 1.0, 1.15]:
                audio = tts_to_array(kokoro, phrase, voice, speed)
                neg_clips.append(audio)
    # Add silence and noise
    for _ in range(20):
        neg_clips.append(np.random.randn(SAMPLE_RATE * 2).astype(np.float32) * 0.01)
    print(f"  {len(neg_clips)} negative clips generated.")

    # ── Extract embeddings ─────────────────────────────────────────────────────
    print("\nExtracting embeddings…")

    def clips_to_features(clips: list[np.ndarray]) -> np.ndarray:
        feats = []
        for audio in clips:
            oww.reset()
            n = len(audio) // CHUNK
            preds = []
            for i in range(n):
                chunk = audio[i*CHUNK:(i+1)*CHUNK]
                p = oww.predict(chunk)
                # Use the raw scores as features
                score = list(p.values())[0] if p else 0.0
                if isinstance(score, dict):
                    score = max(score.values()) if score else 0.0
                preds.append(float(score))
            # Feature = [mean_score, max_score, std_score, len_chunks]
            preds = np.array(preds) if preds else np.array([0.0])
            feats.append([
                float(np.mean(preds)),
                float(np.max(preds)),
                float(np.std(preds)),
                float(len(preds)),
                float(np.percentile(preds, 90)),
                float(np.sum(preds > 0.3)),
            ])
        return np.array(feats)

    print("  Positive…")
    X_pos = clips_to_features(pos_clips)
    print("  Negative…")
    X_neg = clips_to_features(neg_clips)

    X = np.vstack([X_pos, X_neg])
    y = np.array([1] * len(X_pos) + [0] * len(X_neg))

    # ── Train ──────────────────────────────────────────────────────────────────
    print("\nTraining classifier…")
    clf = Pipeline([
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000)),
    ])
    clf.fit(X, y)

    # Quick eval
    preds = clf.predict(X)
    print(classification_report(y, preds, target_names=["negative", "hey_cortana"]))

    # ── Save ───────────────────────────────────────────────────────────────────
    joblib.dump(clf, MODEL_OUT)
    print(f"\nModel saved → {MODEL_OUT}")
    print("Updating config…")

    # Patch config
    cfg_path = Path(__file__).parent.parent / "config" / "cortana.yaml"
    text = cfg_path.read_text()
    text = text.replace(
        "  wake_word: \"hey_jarvis_v0.1\"",
        "  wake_word: \"hey_cortana\"",
    )
    cfg_path.write_text(text)
    print("Config updated. Restart with: .venv/bin/cortana start --voice")


def record_samples(phrase: str, n: int) -> list[np.ndarray]:
    clips = []
    for i in range(n):
        input(f"  [{i+1}/{n}] Press Enter then say '{phrase}'… ")
        q: queue.Queue = queue.Queue()
        def cb(indata, frames, t, s): q.put(indata[:, 0].copy())
        frames = []
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                             blocksize=CHUNK, callback=cb):
            end = time.time() + 2.5
            while time.time() < end:
                try: frames.append(q.get(timeout=0.5))
                except queue.Empty: pass
        clips.append(np.concatenate(frames))
        print("    ✓ recorded")
    return clips


if __name__ == "__main__":
    main()
