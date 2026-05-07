from __future__ import annotations

import json
import urllib.error
import urllib.request


class OllamaClient:
    def __init__(self, model: str = "qwen3:8b", base_url: str = "http://localhost:11434") -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")

    def generate_json(self, prompt: str) -> object | None:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0},
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
            text = data.get("response", "")
            return json.loads(text)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
            return None

