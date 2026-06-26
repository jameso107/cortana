"""Central config loader — reads cortana.yaml, exposes typed settings."""
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel


class InferenceConfig(BaseModel):
    host: str = "localhost"
    port: int = 8080
    model: str = "Qwen3-27B-Instruct-Q6_K_M.gguf"
    context_window: int = 16384
    gpu_layers: int = 99
    threads: int = 8
    temperature: float = 0.7
    tool_temperature: float = 0.2
    flash_attention: bool = True


class VoiceConfig(BaseModel):
    stt_model: str = "medium.en"
    tts_engine: str = "kokoro"
    tts_voice: str = "neutral_male"
    vad_threshold: float = 0.5
    silence_ms: int = 800
    push_to_talk_hotkey: str = "cmd+space"


class MemoryConfig(BaseModel):
    episodic_path: str = "~/.cortana/memory/chroma"
    structured_path: str = "~/.cortana/memory/cortana.db"
    embedding_model: str = "nomic-embed-text"
    context_tokens: int = 2048
    decay_half_life_days: int = 30


class AgentConfig(BaseModel):
    max_steps: int = 10          # PRD ceiling is 20; 10 is a safe local default
    inject_facts: bool = True    # add stored user facts to the system prompt


class SafetyConfig(BaseModel):
    confirm_destructive: bool = True
    dry_run_default: bool = False
    terminal_allowlist: list[str] = []
    terminal_blocklist: list[str] = ["rm -rf /", "sudo rm"]


class CortanaConfig(BaseModel):
    inference: InferenceConfig = InferenceConfig()
    voice: VoiceConfig = VoiceConfig()
    memory: MemoryConfig = MemoryConfig()
    agent: AgentConfig = AgentConfig()
    safety: SafetyConfig = SafetyConfig()

    @classmethod
    def load(cls, path: Path | None = None) -> "CortanaConfig":
        if path is None:
            path = Path(__file__).parent.parent / "config" / "cortana.yaml"
        if not path.exists():
            return cls()
        raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
        return cls(**raw)


_config: CortanaConfig | None = None


def get_config() -> CortanaConfig:
    global _config
    if _config is None:
        _config = CortanaConfig.load()
    return _config
