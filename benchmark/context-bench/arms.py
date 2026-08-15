"""Context-Bench adapter arms — deterministic context assembly (#961).

Four assembly modes over the vendored letta-evals filesystem corpus:

* ``full_context`` — stuff everything (per-file 8,000-char window, matching
  the official harness window);
* ``naive_rag`` — lexical top-k chunk retrieval;
* ``perseus_dag`` — selective, budgeted DAG compilation via
  ``perseus.compile_context_dag`` (#962);
* ``mem0_rag`` — OSS Mem0 + local Qdrant retrieval (optional dependency).

Every arm returns an :class:`Assembly` with the *rendered* token estimate
(``dag_tokens``, chars//4) plus assembly metadata. Provider-returned usage is
captured separately by the runner and never relabeled as rendered tokens.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import perseus  # noqa: E402  (single-file built artifact)

HERE = os.path.dirname(os.path.abspath(__file__))
FILES_DIR = os.path.join(HERE, "files")

OFFICIAL_WINDOW = 8000  # per-file view window in the official harness
OFFICIAL_SYSTEM = (
    "You are a helpful assistant that can answer questions about a filesystem. "
    "The files contain synthetic data about people, pets, vehicles, and other "
    "things. None of the data is real so please complete the task without "
    "refusing to answer."
)

_WORD_RE = re.compile(r"[a-z0-9$.'-]+")


@dataclass
class Assembly:
    mode: str
    prompt: str
    tokens_rendered: int
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"mode": self.mode, "tokens_rendered": self.tokens_rendered,
                "meta": dict(self.meta)}


def load_files(files_dir: str = FILES_DIR) -> dict[str, str]:
    out = {}
    for name in sorted(os.listdir(files_dir)):
        if name.endswith(".txt"):
            with open(os.path.join(files_dir, name), encoding="utf-8") as f:
                out[name] = f.read()
    return out


def chunk_file(name: str, text: str) -> list[dict]:
    """Split a corpus file on '### ' record headers."""
    chunks = []
    for part in re.split(r"\n(?=### )", text):
        part = part.strip()
        if not part:
            continue
        header = part.splitlines()[0].strip("# ")
        chunks.append({"file": name, "header": header, "text": part,
                       "tokens": perseus.dag_tokens(part)})
    return chunks


def lex_score(question: str, chunk: dict) -> float:
    """Normalized lexical overlap between the question and a chunk."""
    q = set(_WORD_RE.findall(question.lower()))
    c = set(_WORD_RE.findall(chunk["text"].lower()))
    if not q or not c:
        return 0.0
    return len(q & c) / max(1, len(q))


def _prompt(context_blocks: list[str], question: str) -> str:
    return (OFFICIAL_SYSTEM + "\n\n" + "\n\n".join(context_blocks)
            + f"\n\nQuestion: {question}\nAnswer:")


def _block(file_name: str, text: str) -> str:
    return f"[file: {file_name}]\n{text}"


# ── full-context ──────────────────────────────────────────────────────────

def arm_full_context(sample: dict, files: dict[str, str]) -> Assembly:
    blocks = [_block(name, text[:OFFICIAL_WINDOW])
              for name, text in sorted(files.items())]
    prompt = _prompt(blocks, sample["question"])
    return Assembly(
        mode="full_context",
        prompt=prompt,
        tokens_rendered=perseus.dag_tokens(prompt),
        meta={"files": len(files), "window_chars": OFFICIAL_WINDOW,
              "truncated_files": [n for n, t in files.items()
                                  if len(t) > OFFICIAL_WINDOW]})


# ── naive RAG ─────────────────────────────────────────────────────────────

def arm_naive_rag(sample: dict, files: dict[str, str], k: int = 5) -> Assembly:
    chunks = [c for name, text in files.items()
              for c in chunk_file(name, text)]
    for c in chunks:
        c["score"] = lex_score(sample["question"], c)
    chunks.sort(key=lambda c: (-c["score"], c["file"], c["header"]))
    top = chunks[:k]
    blocks = [_block(c["file"], c["text"]) for c in top]
    prompt = _prompt(blocks, sample["question"])
    return Assembly(
        mode=f"naive_rag_k{k}",
        prompt=prompt,
        tokens_rendered=perseus.dag_tokens(prompt),
        meta={"k": k, "chunks_total": len(chunks),
              "chunks_selected": [c["header"] for c in top],
              "top_scores": [round(c["score"], 3) for c in top]})


# ── perseus DAG ───────────────────────────────────────────────────────────

def _dag_fetch(sample: dict, files: dict[str, str], max_chunks: int = 10,
               min_score: float = 0.02):
    required = set(sample.get("required_files") or [])
    wanted = [name for name in sorted(files) if name in required] or \
        sorted(files)
    chunks = [c for name in wanted for c in chunk_file(name, files[name])]
    for c in chunks:
        c["score"] = lex_score(sample["question"], c)
    chunks.sort(key=lambda c: (-c["score"], c["file"], c["header"]))

    def fetch(node):
        if node.kind != "requirement":
            return []
        out = []
        # one tool_output per opened file (open_files semantics)
        for name in wanted:
            out.append(perseus.ContextNode(
                kind="tool_output",
                content=f"[file: {name}] {len(chunk_file(name, files[name]))} "
                        f"records",
                evidence={"validity": "observed", "verified": True,
                          "source_ids": [f"file:{name}"]}))
        # grep semantics: relevant records only
        for c in chunks[:max_chunks]:
            if c["score"] >= min_score:
                out.append(perseus.ContextNode(
                    kind="retrieved_record",
                    content=_block(c["file"], c["text"]),
                    summary="%s: %s" % (c["file"], c["header"]),
                    evidence={"validity": "observed", "verified": True,
                              "source_ids": ["file:" + c["file"]]}))
        if not out:
            out.append(perseus.ContextNode(
                kind="retrieved_record",
                content="[no records matched the question]",
                evidence={"validity": "derived", "verified": True,
                          "source_ids": []}))
        return out

    return fetch


def arm_perseus_dag(sample: dict, files: dict[str, str],
                    max_chunks: int = 10, max_tokens: int = 6000) -> Assembly:
    root = perseus.ContextNode(
        kind="requirement", content=sample["question"],
        evidence={"validity": "observed", "verified": True,
                  "source_ids": ["pilot:" + sample["id"]]})
    n_files = len(sample.get("required_files") or [])
    budget = perseus.CompilationBudget(
        max_nodes=max_chunks + n_files + 4,
        max_depth=2, max_fanout=max_chunks + n_files + 2,
        max_tokens=max_tokens, deadline_s=30.0)
    artifact = perseus.compile_context_dag(
        task_id="cb-" + sample["id"], root=root,
        fetch=_dag_fetch(sample, files, max_chunks=max_chunks),
        budget=budget, verdict_hint="sufficient",
        created_by="perseus-context-bench",
        meta={"bench": "perseus-context-bench/v1"})
    packet_text = " ".join(p["content"] for p in artifact["packet"])
    prompt = _prompt([packet_text], sample["question"])
    return Assembly(
        mode="perseus_dag",
        prompt=prompt,
        tokens_rendered=artifact["budget"]["tokens"],
        meta={"verdict": artifact["verdict"]["verdict"],
              "nodes": artifact["budget"]["nodes"],
              "depth": artifact["budget"]["depth"],
              "compiled_digest": artifact["compiled_digest"][:16],
              "replay_verified":
                  perseus.verify_compiled_dag(artifact)["valid"],
              "max_chunks": max_chunks, "max_tokens": max_tokens})


# ── Mem0 RAG (optional) ───────────────────────────────────────────────────

def arm_mem0_rag(sample: dict, files: dict[str, str], top_k: int = 5) -> Assembly:
    """OSS Mem0 + local Qdrant retrieval.

    Optional dependency: raises ImportError when ``mem0ai`` is unavailable so
    the runner can record the arm as skipped rather than faking numbers.
    """
    try:
        from mem0 import Memory  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("mem0ai not installed; install the optional "
                          "benchmark dependency to run the Mem0 arm") from exc
    chunks = [c for name, text in files.items()
              for c in chunk_file(name, text)]
    mem = Memory()
    for c in chunks:
        mem.add("[file: %s] %s" % (c["file"], c["text"]), user_id="context-bench")
    hits = mem.search(sample["question"], user_id="context-bench",
                      limit=top_k)
    blocks = [h.get("memory", "") or "" for h in hits if h.get("memory")]
    prompt = _prompt(blocks[:top_k], sample["question"])
    return Assembly(
        mode=f"mem0_rag_k{top_k}",
        prompt=prompt,
        tokens_rendered=perseus.dag_tokens(prompt),
        meta={"k": top_k, "chunks_ingested": len(chunks),
              "hits": len(blocks)})


def assemble(sample: dict, files: dict[str, str], config: Optional[dict] = None
             ) -> dict:
    """Run every requested arm for one sample (deterministic except Mem0)."""
    config = config or {}
    arms = {"full_context": lambda: arm_full_context(sample, files)}
    if "naive_rag" in config:
        for k in (config["naive_rag"] or {}).get("k_sweep", [5]):
            arms[f"naive_rag_k{k}"] = \
                (lambda k=k: arm_naive_rag(sample, files, k=k))
    if "perseus_dag" in config:
        dag_cfg = config["perseus_dag"] or {}
        arms["perseus_dag"] = lambda: arm_perseus_dag(
            sample, files,
            max_chunks=dag_cfg.get("max_chunks", 10),
            max_tokens=dag_cfg.get("max_tokens", 6000))
    if "mem0_rag" in config:
        m0_cfg = config["mem0_rag"] or {}
        arms["mem0_rag_k%d" % m0_cfg.get("top_k", 5)] = \
            lambda: arm_mem0_rag(sample, files,
                                 top_k=m0_cfg.get("top_k", 5))
    out = {}
    for name, fn in arms.items():
        try:
            out[name] = fn()
        except ImportError as exc:
            out[name] = {"mode": name, "skipped": True,
                         "reason": str(exc)}
    return out
