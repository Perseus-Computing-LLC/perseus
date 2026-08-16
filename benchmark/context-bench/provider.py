"""OpenAI-compatible chat client (stdlib-only) for the Context-Bench run (#961).

Freezes provider-returned usage telemetry; never estimates it. Endpoint, model,
and key are resolved from environment at call time so no credential ever lands
in a file or artifact:

* ``CB_ANSWER_ENDPOINT`` / ``CB_ANSWER_MODEL`` / ``CB_ANSWER_KEY_ENV`` — the
  agent-under-test arm;
* ``CB_JUDGE_ENDPOINT`` / ``CB_JUDGE_MODEL`` / ``CB_JUDGE_KEY_ENV`` — the
  rubric judge (official contract: gpt-5-mini, temperature 0).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Optional


class ChatClient:
    def __init__(self, *, role: str, endpoint: str, model: str,
                 key_env: str, temperature: float = 0.0,
                 max_tokens: int = 2048, timeout_s: float = 300.0,
                 reasoning_effort: Optional[str] = None):
        self.role = role
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.key_env = key_env
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.timeout_s = float(timeout_s)
        self.reasoning_effort = reasoning_effort
        key = os.environ.get(key_env, "")
        if not key:
            raise RuntimeError(f"{key_env} is not set for {role}")
        self._auth = f"Bearer {key}"

    def complete(self, prompt: str,
                 max_tokens: Optional[int] = None) -> dict:
        """One chat completion; returns content + provider usage verbatim.

        Reasoning-capable models (gpt-5*, o-series) reject the legacy
        ``max_tokens`` parameter with HTTP 400 and require
        ``max_completion_tokens`` instead.
        """
        cap = max_tokens or self.max_tokens
        if self.model.startswith(("gpt-5", "o1", "o3", "o4")):
            cap_key, cap_val = "max_completion_tokens", cap
        else:
            cap_key, cap_val = "max_tokens", cap
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            cap_key: cap_val,
        }
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        req = urllib.request.Request(
            self.endpoint, data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": self._auth,
                     "Content-Type": "application/json",
                     "User-Agent": "perseus-context-bench"},
            method="POST")
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                data = json.load(r)
        except urllib.error.HTTPError as exc:
            return {"error": f"http {exc.code}",
                    "detail": exc.read()[:200].decode(errors="replace")}
        except Exception as exc:  # noqa: BLE001 — bounded, sanitized
            return {"error": type(exc).__name__, "detail": str(exc)[:200]}
        elapsed = round(time.time() - started, 3)
        try:
            message = data["choices"][0]["message"]
            content = message.get("content")
            finish = data["choices"][0].get("finish_reason")
            usage = data.get("usage")
        except (KeyError, IndexError, TypeError):
            return {"error": "malformed provider response",
                    "detail": json.dumps(data)[:200]}
        out = {"content": content or "", "finish_reason": finish,
               "usage": usage, "latency_s": elapsed,
               "model": self.model, "endpoint_host":
                   self.endpoint.split("//")[-1].split("/")[0]}
        if content is None:
            out["error"] = "null content"
        return out

    def describe(self) -> dict:
        """Public-safe config description (no key material)."""
        return {"role": self.role, "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "reasoning_effort": self.reasoning_effort,
                "endpoint_host": self.endpoint.split("//")[-1].split("/")[0],
                "key_env": self.key_env}


class MockChatClient:
    """Deterministic provider stand-in for dry runs (never emits real data)."""

    def __init__(self, *, role: str, salt: str = "dry-run"):
        self.role = role
        self.salt = salt
        self.calls = 0

    def complete(self, prompt: str,
                 max_tokens: Optional[int] = None) -> dict:
        import hashlib
        self.calls += 1
        h = hashlib.sha256((self.salt + prompt).encode()).hexdigest()
        content = f"mock-answer-{h[:16]}"
        return {"content": content, "finish_reason": "stop",
                "usage": {"prompt_tokens": max(1, len(prompt) // 4),
                          "completion_tokens": 8,
                          "total_tokens": max(1, len(prompt) // 4) + 8},
                "latency_s": 0.001, "model": f"mock-{self.role}",
                "endpoint_host": "mock"}

    def describe(self) -> dict:
        return {"role": self.role, "model": f"mock-{self.role}",
                "mock": True, "salt": self.salt}
