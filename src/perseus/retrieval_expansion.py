"""LLM-driven retrieval query expansion (#580).

The client-side half of the weak-category recall fix. A memory retriever scores
one verbatim query against past sessions, but the answer usually lives in a
session whose words don't overlap the question (2-hop questions, synonym gaps,
"count all X" aggregation). This turns a question into a *plan* — decomposed and
expanded sub-queries — so the connector can issue one recall per sub-query and
fuse the hits with Reciprocal Rank Fusion.

Validated on LongMemEval: weak-category recall@10 0.90 -> 0.99, multi-session
full-coverage 84% -> 95% (see benchmark/longmemeval). Works on a cheap model
(gpt-4o-mini class).

Design constraints:
* **Optional.** Off by default; when disabled the connector's single-query
  recall is byte-identical to before. Enable via config `mneme.expansion`.
* **Model-agnostic.** Any OpenAI-compatible ``/v1/chat/completions`` endpoint
  (OpenAI, Ollama, vLLM, ...).
* **No new dependency.** Uses stdlib ``urllib`` — Perseus gains no runtime dep.
* **Fail-safe.** Any planner error returns ``None``; the caller falls back to a
  plain single-query recall. Retrieval never breaks because expansion hiccuped.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

# The planner prompt — validated against the #580 hard-miss cases. Emits queries
# phrased as the *underlying fact the user likely wrote*, not restatements.
_SYSTEM_PROMPT = (
    "You plan retrieval queries for a long-term conversational memory system.\n\n"
    "The retriever matches a query against the USER's own words in past chat "
    "sessions. The catch: the answer to a question usually lives in a session "
    "whose words do NOT overlap the question (e.g. \"How old was I when Alex was "
    "born?\" -> the user's age lives in a session where they said \"I just turned "
    "32\"; \"How many doctors did I visit?\" -> sessions say \"my ENT specialist\" / "
    "\"my dermatologist\", never \"doctors\").\n\n"
    "Emit queries phrased the way the USER would have written the UNDERLYING "
    "facts. Return STRICT JSON (no prose):\n"
    "{\n"
    '  "sub_queries": [up to 6 short first-person statements of an underlying '
    "fact the user likely wrote, NOT restatements of the question],\n"
    '  "aggregation": boolean,  // does it ask to count/list/order ALL instances of a topic?\n'
    '  "topic": string|null,    // the subject to retrieve broadly on when aggregation\n'
    '  "date_window": {"from":"YYYY-MM-DD","to":"YYYY-MM-DD"}|null,  // resolve relative dates vs asked_date\n'
    '  "text_query": string     // the question with temporal scaffolding removed\n'
    "}\n\n"
    "Rules:\n"
    "- TWO-FACT questions (\"how old was I when X\") -> one sub-query per fact in "
    "the user's likely words (\"how old is X\", \"I just turned\" / \"my age\").\n"
    "- Expand synonyms/instances: doctors -> physician, specialist, dermatologist, "
    "ENT, appointment; movie <-> film; attended <-> participated / went to.\n"
    "- Counting/listing/ordering -> aggregation=true, topic=the subject.\n"
    "- Resolve relative dates against asked_date; strip the temporal phrase from text_query.\n"
    "- Keep sub_queries short and concrete; prefer the fact over the question."
)


@dataclass
class ExpansionConfig:
    """Config for the optional query-expansion arm (from ``mneme.expansion``)."""
    enabled: bool = False
    endpoint: str = "https://api.openai.com/v1/chat/completions"
    model: str = "gpt-4o-mini"
    api_key: str = ""                 # resolved from api_key_env by the connector
    api_key_env: str = "OPENAI_API_KEY"
    timeout_s: float = 20.0
    max_subqueries: int = 6
    per_query_limit_factor: int = 2   # over-fetch each arm to factor*max_results

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "ExpansionConfig":
        d = d or {}
        return cls(
            enabled=bool(d.get("enabled", False)),
            endpoint=str(d.get("endpoint", cls.endpoint)),
            model=str(d.get("model", cls.model)),
            api_key_env=str(d.get("api_key_env", cls.api_key_env)),
            timeout_s=float(d.get("timeout_s", cls.timeout_s)),
            max_subqueries=int(d.get("max_subqueries", cls.max_subqueries)),
            per_query_limit_factor=int(d.get("per_query_limit_factor",
                                             cls.per_query_limit_factor)),
        )


@dataclass
class QueryPlan:
    sub_queries: list = field(default_factory=list)
    aggregation: bool = False
    topic: Optional[str] = None
    date_window: Optional[dict] = None
    text_query: str = ""

    def query_set(self, original: str) -> list:
        """Ordered, de-duplicated query strings to recall on: sub-queries, the
        aggregation topic, and always the original question as a fallback arm."""
        out, seen = [], set()
        for q in list(self.sub_queries) + ([self.topic] if (self.aggregation and self.topic) else []) + [original]:
            q = (q or "").strip()
            if q and q.lower() not in seen:
                seen.add(q.lower())
                out.append(q)
        return out


def plan_query(question: str, asked_date: str, cfg: ExpansionConfig) -> Optional[QueryPlan]:
    """Ask the configured LLM for a retrieval plan. Returns None on any failure
    (missing key, network, bad JSON) so the caller can fall back to single-query."""
    if not cfg.api_key:
        return None
    body = json.dumps({
        "model": cfg.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"asked_date: {asked_date}\nQUESTION: {question}"},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        cfg.endpoint, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg.api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        raw = json.loads(content)
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError):
        return None
    sub = [s for s in (raw.get("sub_queries") or [])
           if isinstance(s, str) and s.strip()][:cfg.max_subqueries]
    return QueryPlan(
        sub_queries=sub,
        aggregation=bool(raw.get("aggregation")),
        topic=(raw.get("topic") or None),
        date_window=(raw.get("date_window") or None),
        text_query=str(raw.get("text_query") or question),
    )


def rrf_fuse(ranked_id_lists: list, k: float = 60.0) -> list:
    """Reciprocal Rank Fusion over several ranked id lists → one ranked id list.
    Mirrors Vault's own RRF (k=60): score(id) = Σ 1/(k + rank)."""
    scores: dict = {}
    for lst in ranked_id_lists:
        for rank, _id in enumerate(lst):
            if _id is not None:
                scores[_id] = scores.get(_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda i: -scores[i])
