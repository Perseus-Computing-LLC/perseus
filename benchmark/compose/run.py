#!/usr/bin/env python3
"""Perseus context-compiler benchmark (#473) — reproducible, offline.

Measures, for the SAME task over the SAME corpus, the assembled-context **token
count** produced by each tool's idiomatic *offline* assembly, plus two structural
properties of the Perseus compiler:

  paths compared (token efficiency)
    - naive       : concatenate the whole corpus (no context tool at all)
    - langchain   : BM25 retrieval (offline, deterministic) -> stuff top-k chunks
    - llamaindex  : BM25 retrieval (offline, deterministic) -> stuff top-k nodes
    - perseus     : a deterministic `.perseus` compile of the author-declared context

  structural properties (perseus)
    - determinism : the compile is byte-identical across repeated renders (sha256)
    - caching     : cold (no_cache) vs warm (cache hit) render wall-clock

Token counts use **tiktoken** (`cl100k_base`) when installed, else a transparent
`chars/4` estimate (clearly labeled in the output). **No LLM or network calls are
made** — this is a deterministic, one-command, reproducible benchmark.

Usage
    python benchmark/compose/run.py
    python benchmark/compose/run.py --top-k 4 --json out.json

The langchain / llamaindex rows are skipped (with a note) unless their optional
packages are installed:  pip install -r benchmark/compose/requirements.txt

Honesty notes (see README.md for the full methodology):
  * The perseus row reflects an author-declared context spec — Perseus's core value
    is that you *compile* exactly the context you want, deterministically and
    reproducibly. The framework rows reflect idiomatic offline BM25 retrieval; the
    naive row is the no-tool baseline. None of these involve an LLM, so the result
    is about *assembly*, not answer quality.
  * Numbers are produced live by this script on your machine. Nothing is hardcoded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS_DIR = HERE / "corpus"
PERSEUS_SOURCE = HERE / "context.perseus"
# The task an agent needs context for (drives BM25 retrieval in the framework rows).
TASK_QUERY = "What authentication method does the service use and which database backs it?"

# The answer-bearing facts the assembled context MUST contain to actually answer
# the task. Coverage turns this into a quality measure, not just a size measure:
# a smaller context that drops a required fact is worse, not better.
GOLD_FACTS = ["JWT", "RS256", "OAuth 2.0", "PostgreSQL"]


# ─────────────────────────────── repo import ────────────────────────────────
def _import_perseus():
    """Import the built `perseus` module from the repo root (perseus.py)."""
    repo_root = HERE.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        import perseus  # noqa: F401  (built artifact at repo root)
        return perseus
    except Exception as e:  # pragma: no cover - environment issue
        print(f"FATAL: could not import perseus from {repo_root}: {e}", file=sys.stderr)
        print("Run `python scripts/build.py` first to produce perseus.py.", file=sys.stderr)
        raise


# ─────────────────────────────── token counting ─────────────────────────────
def _make_token_counter():
    """Return (count_fn, method_label). Prefer tiktoken; fall back to chars/4."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return (lambda s: len(enc.encode(s)), "tiktoken/cl100k_base")
    except Exception:
        return (lambda s: max(1, len(s) // 4), "estimate(chars/4)")


# ─────────────────────────────── corpus ─────────────────────────────────────
def load_corpus() -> dict[str, str]:
    docs = {}
    for p in sorted(CORPUS_DIR.glob("*.md")):
        docs[p.name] = p.read_text(encoding="utf-8")
    if not docs:
        raise SystemExit(f"no corpus docs found under {CORPUS_DIR}")
    return docs


def chunk_docs(docs: dict[str, str], max_chars: int = 600) -> list[tuple[str, str]]:
    """Split docs into (source_name, chunk_text) on blank-line paragraph boundaries.

    Deterministic, no dependencies — shared by the langchain/llamaindex rows so
    they retrieve over identical chunks."""
    chunks: list[tuple[str, str]] = []
    for name, text in docs.items():
        buf: list[str] = []
        size = 0
        for para in text.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            if size + len(para) > max_chars and buf:
                chunks.append((name, "\n\n".join(buf)))
                buf, size = [], 0
            buf.append(para)
            size += len(para)
        if buf:
            chunks.append((name, "\n\n".join(buf)))
    return chunks


# ─────────────────────────────── paths ──────────────────────────────────────
def path_naive(docs: dict[str, str]) -> str:
    """No context tool: stuff every document into the prompt."""
    parts = [f"# {name}\n\n{text}" for name, text in docs.items()]
    return "\n\n---\n\n".join(parts)


def path_perseus(perseus, runs: int = 5) -> dict:
    """Compile the .perseus source and verify determinism across repeated renders.

    Determinism is checked both in-process (N renders) and the hash is reported so
    a caller can confirm it matches across separate processes / machines.

    (Cold->warm cache speedup is intentionally NOT measured here: this corpus uses
    only cheap @include directives, for which the cache adds overhead without
    benefit. The existing benchmark/ suites measure cold->warm for the directives
    that actually pay for caching — @query / @mimir. See README.)"""
    import copy
    cfg = copy.deepcopy(perseus.DEFAULT_CONFIG)
    source = PERSEUS_SOURCE.read_text(encoding="utf-8")
    workspace = HERE

    hashes = []
    output = ""
    for _ in range(runs):
        output = perseus.render_source(source, cfg, workspace, no_cache=True)
        hashes.append(hashlib.sha256(output.encode("utf-8")).hexdigest())
    deterministic = len(set(hashes)) == 1

    return {
        "output": output,
        "deterministic": deterministic,
        "sha256": hashes[0],
        "runs": runs,
    }


def path_langchain(chunks: list[tuple[str, str]], query: str, top_k: int) -> str | None:
    """LangChain idiomatic offline assembly: BM25 retrieve top-k, stuff into a prompt."""
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from langchain_community.retrievers import BM25Retriever
        from langchain_core.documents import Document
        from langchain_core.prompts import PromptTemplate
    except Exception:
        return None
    lc_docs = [Document(page_content=c, metadata={"source": n}) for n, c in chunks]
    retriever = BM25Retriever.from_documents(lc_docs, k=top_k)
    hits = retriever.invoke(query)
    context = "\n\n".join(d.page_content for d in hits)
    # The canonical "stuff" prompt: the assembled context dropped into a template.
    tmpl = PromptTemplate.from_template("Use the context to answer.\n\nContext:\n{context}\n\nQuestion: {q}")
    return tmpl.format(context=context, q=query)


def path_llamaindex(chunks: list[tuple[str, str]], query: str, top_k: int) -> str | None:
    """LlamaIndex idiomatic offline assembly: BM25 retrieve top-k nodes, stuff into the QA prompt."""
    try:
        from llama_index.core.schema import TextNode, NodeWithScore
        from llama_index.retrievers.bm25 import BM25Retriever
        from llama_index.core.prompts import PromptTemplate
    except Exception:
        return None
    nodes = [TextNode(text=c, metadata={"source": n}) for n, c in chunks]
    try:
        retriever = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=top_k)
        hits = retriever.retrieve(query)
    except Exception:
        return None
    context = "\n\n".join(h.get_content() for h in hits)
    tmpl = PromptTemplate(
        "Context information is below.\n---------------------\n{context_str}\n"
        "---------------------\nGiven the context, answer: {query_str}\n"
    )
    return tmpl.format(context_str=context, query_str=query)


# ─────────────────────────────── runner ─────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top-k", type=int, default=4, help="chunks retrieved by the framework rows")
    ap.add_argument("--json", type=str, default=str(HERE / "results.json"), help="results JSON output path")
    args = ap.parse_args()

    perseus = _import_perseus()
    count, token_method = _make_token_counter()
    docs = load_corpus()
    chunks = chunk_docs(docs)

    naive = path_naive(docs)
    per = path_perseus(perseus)
    lc = path_langchain(chunks, TASK_QUERY, args.top_k)
    li = path_llamaindex(chunks, TASK_QUERY, args.top_k)

    naive_tok = count(naive)

    def reduction(tok: int) -> float:
        return (1 - tok / naive_tok) * 100 if naive_tok else 0.0

    def coverage(text: str) -> tuple[int, int]:
        present = sum(1 for f in GOLD_FACTS if f.lower() in text.lower())
        return present, len(GOLD_FACTS)

    rows = []  # (name, tokens|None, reduction|None, cov_present, cov_total, notes)
    rows.append(("naive (stuff all docs)", naive_tok, 0.0, *coverage(naive), "—"))
    if lc is not None:
        t = count(lc)
        rows.append((f"langchain (BM25 top-{args.top_k})", t, reduction(t), *coverage(lc), "deterministic*"))
    else:
        rows.append((f"langchain (BM25 top-{args.top_k})", None, None, 0, len(GOLD_FACTS), "skipped (not installed)"))
    if li is not None:
        t = count(li)
        rows.append((f"llamaindex (BM25 top-{args.top_k})", t, reduction(t), *coverage(li), "deterministic*"))
    else:
        rows.append((f"llamaindex (BM25 top-{args.top_k})", None, None, 0, len(GOLD_FACTS), "skipped (not installed)"))
    per_tok = count(per["output"])
    rows.append(("perseus (compiled)", per_tok, reduction(per_tok), *coverage(per["output"]),
                 "deterministic ✓" if per["deterministic"] else "NON-DETERMINISTIC ✗"))

    # ── print table ──
    print()
    print(f"Perseus context-compiler benchmark — token method: {token_method}")
    print(f"Corpus: {len(docs)} docs, {len(chunks)} chunks · Task: {TASK_QUERY!r}")
    print(f"Answer-coverage facts ({len(GOLD_FACTS)}): {', '.join(GOLD_FACTS)}")
    print("=" * 84)
    print(f"{'path':<34}{'tokens':>9}{'vs naive':>11}{'answer cov':>12}  {'notes'}")
    print("-" * 84)
    for name, tok, red, cov_p, cov_t, note in rows:
        if tok is None:
            print(f"{name:<34}{'—':>9}{'—':>11}{'—':>12}  {note}")
        else:
            red_s = f"-{red:.1f}%" if red > 0 else "baseline"
            cov_s = f"{cov_p}/{cov_t}"
            print(f"{name:<34}{tok:>9}{red_s:>11}{cov_s:>12}  {note}")
    print("-" * 84)
    print(f"perseus determinism : {('byte-identical across %d renders ✓' % per['runs']) if per['deterministic'] else 'FAILED ✗'}  (sha256 {per['sha256'][:12]})")
    print("=" * 84)
    print("* framework rows are deterministic here only because retrieval is offline BM25;")
    print("  with embedding/LLM assembly they are not. Perseus is deterministic by design.")
    print()

    # ── write results.json ──
    result = {
        "task": TASK_QUERY,
        "token_method": token_method,
        "corpus_docs": len(docs),
        "chunks": len(chunks),
        "top_k": args.top_k,
        "naive_tokens": naive_tok,
        "gold_facts": GOLD_FACTS,
        "rows": [
            {"path": n, "tokens": t, "reduction_pct": (round(r, 1) if r is not None else None),
             "answer_coverage": f"{cp}/{ct}", "notes": note}
            for (n, t, r, cp, ct, note) in rows
        ],
        "perseus": {
            "tokens": per_tok,
            "deterministic": per["deterministic"],
            "sha256": per["sha256"],
            "determinism_runs": per["runs"],
        },
    }
    Path(args.json).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"results -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
