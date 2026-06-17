from __future__ import annotations
import os, subprocess as sp
from pathlib import Path
from agent.context_engine import ContextEngine

def get_compressor():
    from agent.context_compressor import ContextCompressor
    return ContextCompressor

class PerseusContextEngine(ContextEngine):
    def __init__(self, model="__placeholder__", **kwargs):
        self._compressor = get_compressor()(model=model, **kwargs)
        for a in ["last_prompt_tokens", "last_completion_tokens", "last_total_tokens", "threshold_tokens", "context_length", "compression_count"]:
            setattr(self, a, 0)
        self._perseus_context = ""
        self._perseus_path = None
        hh = os.getenv("HERMES_HOME", "")
        paths = [Path(hh)/"plugins"/"perseus", Path.home()/".hermes"/"plugins"/"perseus"]
        for p in paths:
            if (p/"perseus.py").exists():
                self._perseus_path = p.resolve()
                break
    @property
    def name(self): return "perseus"
    def update_from_response(self, u): self._compressor.update_from_response(u); self._sync()
    def should_compress(self, p=None): return self._compressor.should_compress(p)
    def compress(self, m, c=None, f=None): return self._compressor.compress(m, c, f)
    def on_session_start(self, s, **k):
        self._compressor.on_session_start(s, **k)
        if self._perseus_path:
            parts = []
            ctx_md = self._perseus_path/".perseus"/"context.md"
            if ctx_md.exists(): parts.append(ctx_md.read_text(encoding="utf-8"))
            try:
                env = os.environ.copy(); env["PERSEUS_ALLOW_DANGEROUS"] = "1"
                r = sp.run([os.getenv("HERMES_PYTHON","python3"), str(self._perseus_path/"perseus.py"), "doctor", "--json"], capture_output=True, text=True, timeout=10, cwd=str(self._perseus_path), env=env)
                if r.returncode == 0 and r.stdout.strip(): parts.insert(0, "## Perseus Live Context\n\n" + r.stdout.strip())
            except: pass
            self._perseus_context = "\n\n".join(parts)
        self._sync()
    def on_session_reset(self): self._compressor.on_session_reset(); self._perseus_context = ""; self._sync()
    def get_tool_schemas(self):
        # Return the BARE inner tool spec. The Hermes harness wraps this in
        # {"type": "function", "function": <spec>} itself (agent/agent_init.py).
        # Returning a pre-wrapped schema double-wraps it -> function.function.name,
        # which strict providers (DeepSeek) reject with HTTP 400. See
        # NousResearch/hermes-agent#47707.
        return [{"name": "perseus_grep", "description": "Search context.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}]
    def handle_tool_call(self, n, a, **k):
        import json
        if n == "perseus_grep":
            q = (a.get("query") or "").lower()
            lines = self._perseus_context.split("\n")
            matches = [{"line": i+1, "content": l[:200]} for i,l in enumerate(lines) if q in l.lower()]
            return json.dumps({"matches": matches[:20]})
        return json.dumps({"error": "unknown"})
    def update_model(self, model, context_length, **k): self._compressor.update_model(model, context_length, **k); self._sync()
    def _sync(self):
        for a in ["last_prompt_tokens", "last_completion_tokens", "last_total_tokens", "threshold_tokens", "context_length", "compression_count"]:
            if hasattr(self._compressor, a): setattr(self, a, getattr(self._compressor, a))
    def get_session_context(self): return self._perseus_context
    @staticmethod
    def is_available():
        hh = os.getenv("HERMES_HOME", "")
        return (Path(hh)/"plugins"/"perseus"/"perseus.py").exists() or (Path.home()/".hermes"/"plugins"/"perseus"/"perseus.py").exists()

def register(ctx):
    try:
        ctx.register_context_engine(PerseusContextEngine())
    except:
        pass
