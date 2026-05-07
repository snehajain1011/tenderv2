from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from llm_client import OllamaClient


@dataclass(frozen=True)
class ModelConfig:
    key: str
    provider: str
    model: str
    endpoint: str = "http://localhost:11434"


class ModelRegistry:
    def __init__(self, configs: dict[str, ModelConfig]) -> None:
        self.configs = configs

    @classmethod
    def from_file(cls, path: Path) -> "ModelRegistry":
        if not path.exists():
            return cls.default()
        configs: dict[str, ModelConfig] = {}
        current: dict[str, str] = {}
        current_key = ""
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line == "models:":
                continue
            if line.endswith(":") and not line.startswith("-"):
                if current_key and current:
                    configs[current_key] = _config(current_key, current)
                current_key = line[:-1]
                current = {}
            elif ":" in line and current_key:
                key, value = line.split(":", 1)
                current[key.strip()] = value.strip().strip('"')
        if current_key and current:
            configs[current_key] = _config(current_key, current)
        return cls(configs or cls.default().configs)

    @classmethod
    def default(cls) -> "ModelRegistry":
        return cls(
            {
                "reasoning": ModelConfig("reasoning", "ollama", "qwen3:8b"),
                "vision": ModelConfig("vision", "ollama", "qwen2.5vl:7b"),
                "embeddings": ModelConfig("embeddings", "local", "term-frequency"),
            }
        )

    def client(self, key: str):
        config = self.configs.get(key)
        if not config or config.provider != "ollama":
            return None
        return OllamaClient(model=config.model, base_url=config.endpoint)


def _config(key: str, raw: dict[str, str]) -> ModelConfig:
    return ModelConfig(
        key=key,
        provider=raw.get("provider", "ollama"),
        model=raw.get("model", "qwen3:8b"),
        endpoint=raw.get("endpoint", "http://localhost:11434"),
    )
