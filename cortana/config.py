"""Central config loader — reads cortana.yaml, exposes typed settings."""
from pathlib import Path
from typing import Any
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env.local")


class InferenceConfig(BaseModel):
    model: str = "gpt-5.5"
    api_key_env: str = "OPENAI_API_KEY"
    reasoning_effort: str = "medium"
    max_output_tokens: int = 6000
    store: bool = True
    embeddings_model: str = "text-embedding-3-small"


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
    embedding_model: str = "text-embedding-3-small"
    context_tokens: int = 2048
    decay_half_life_days: int = 30


class PluginsConfig(BaseModel):
    directory: str = "~/.cortana/plugins"        # third-party plugins
    builtin_directory: str = "cortana/plugins/builtin"
    enabled: list[str] = []                       # if non-empty, allowlist (builtins by name)
    disabled: list[str] = []                      # never load these
    load_third_party: bool = True                 # load hash-approved plugins from `directory`


class AgentConfig(BaseModel):
    max_steps: int = 10          # PRD ceiling is 20; 10 is a safe local default
    inject_facts: bool = True    # add stored user facts to the system prompt
    reasoning: str = "auto"      # "auto" | "always" | "never" — Qwen3 thinking mode


class SafetyConfig(BaseModel):
    confirm_destructive: bool = True
    dry_run_default: bool = False
    terminal_allowlist: list[str] = []
    terminal_blocklist: list[str] = ["rm -rf /", "sudo rm"]
    encrypt_memory: bool = True  # encrypt structured memory at rest (Keychain-backed)


class CortanaConfig(BaseModel):
    inference: InferenceConfig = InferenceConfig()
    voice: VoiceConfig = VoiceConfig()
    memory: MemoryConfig = MemoryConfig()
    agent: AgentConfig = AgentConfig()
    plugins: PluginsConfig = PluginsConfig()
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
