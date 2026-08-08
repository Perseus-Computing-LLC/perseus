"""Portable machine-legible context artifacts and deterministic cartridges (#923/#924/#928)."""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Mapping

_CA_SCHEMA = "perseus-agent-context/v1"
_CA_MEMENTO_SCHEMA = "perseus-memento/v1"
_CA_CARTRIDGE_SCHEMA = "perseus-context-cartridge/v1"
_CA_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+\-]{0,159}$")
_CA_TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:/#@+\-]*")
_CA_STOP = frozenset({"a", "an", "and", "are", "be", "for", "from", "in", "is", "of", "on", "or", "the", "to", "use", "with"})


class ContextArtifactError(ValueError):
    """Raised when a portable artifact cannot satisfy its contract."""


def _ca_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _ca_sha(value: Any) -> str:
    return hashlib.sha256(_ca_json(value).encode("utf-8")).hexdigest()


def _ca_text(value: Any, field: str, limit: int = 512) -> str:
    if not isinstance(value, str):
        raise ContextArtifactError(f"{field} must be text")
    text = re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()
    if not text:
        raise ContextArtifactError(f"{field} must not be empty")
    return text[:limit]


def _ca_id(value: Any, field: str, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    if not text:
        raise ContextArtifactError(f"{field} must not be empty")
    if len(text) > 160 or not _CA_ID.fullmatch(text):
        return "sha256:" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return text


def _ca_digest(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ContextArtifactError("sha256 must be a 64-hex digest")
    return text


def _ca_list(values: Any, field: str, limit: int = 32) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise ContextArtifactError(f"{field} must be a list")
    result = []
    for value in values[:limit]:
        if isinstance(value, str) and value.strip():
            result.append(_ca_text(value, field, 384))
    return result


def _ca_entity(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContextArtifactError("entities must contain objects")
    allowed = ("id", "type", "label", "summary", "source_ref", "content_sha256", "line_range")
    item: dict[str, Any] = {"id": _ca_id(value.get("id"), "entity.id", fallback=f"entity-{index + 1}")}
    for key in allowed[1:]:
        raw = value.get(key)
        if key == "content_sha256":
            digest = _ca_digest(raw)
            if digest:
                item[key] = digest
        elif key == "line_range":
            if isinstance(raw, (list, tuple)) and len(raw) == 2 and all(isinstance(n, int) and not isinstance(n, bool) and n >= 1 for n in raw):
                item[key] = [int(raw[0]), int(raw[1])]
        elif raw is not None and str(raw).strip():
            item[key] = _ca_id(raw, f"entity.{key}") if key in {"type", "source_ref"} else _ca_text(raw, f"entity.{key}", 384)
    # Raw body/content/prompt keys are deliberately not copied.
    return item


def _ca_source(value: Any, index: int) -> dict[str, Any]:
    if isinstance(value, str):
        return {"ref": _ca_id(value, "source.ref")}
    if not isinstance(value, Mapping):
        raise ContextArtifactError("sources must contain objects or refs")
    ref = value.get("ref", value.get("source_id", f"source-{index + 1}"))
    item = {"ref": _ca_id(ref, "source.ref")}
    digest = _ca_digest(value.get("sha256", value.get("content_sha256")))
    if digest:
        item["sha256"] = digest
    if isinstance(value.get("line_range"), (list, tuple)) and len(value["line_range"]) == 2 and all(isinstance(n, int) and n >= 1 for n in value["line_range"]):
        item["line_range"] = [int(value["line_range"][0]), int(value["line_range"][1])]
    return item


def _ca_budgeted(value: dict[str, Any], budget_tokens: int | None) -> tuple[dict[str, Any], dict[str, Any]]:
    budget = max(1, int(budget_tokens)) if budget_tokens is not None else None
    body = dict(value)
    estimated = max(1, math.ceil(len(_ca_json(body).encode("utf-8")) / 4))
    if budget is None or estimated <= budget:
        return body, {"max_tokens": budget, "estimated_tokens": estimated, "within_budget": True, "truncated": False}
    sections = dict(body.get("sections", {}))
    # Preserve intent/objective and evidence anchors first; remove lower-signal
    # lists deterministically until the serialized artifact fits.
    for key in ("examples", "entities", "constraints", "unresolved_questions", "next_steps"):
        if isinstance(sections.get(key), list):
            sections[key] = sections[key][: max(1, min(4, len(sections[key])))]
            body["sections"] = sections
            estimated = math.ceil(len(_ca_json(body).encode("utf-8")) / 4)
            if estimated <= budget:
                break
    if estimated > budget:
        for key in ("intent", "objective", "selection_reason"):
            if isinstance(sections.get(key), str):
                keep = max(8, budget * 3 // 4)
                sections[key] = sections[key][:keep].rstrip() + "…"
        body["sections"] = sections
        estimated = math.ceil(len(_ca_json(body).encode("utf-8")) / 4)
    if estimated > budget:
        raise ContextArtifactError("artifact cannot fit declared token budget without dropping required intent")
    return body, {"max_tokens": budget, "estimated_tokens": estimated, "within_budget": True, "truncated": True}


def _ca_finalize(schema: str, kind: str, sections: dict[str, Any], *, budget_tokens: int | None = None) -> dict[str, Any]:
    present = sum(bool(value) for value in sections.values())
    quality = {
        "field_coverage": round(present / max(1, len(sections)), 4),
        "ambiguity_count": len(sections.get("unresolved_questions", [])) if isinstance(sections.get("unresolved_questions"), list) else 0,
        "citation_density": round(len(sections.get("evidence_anchors", sections.get("sources", []))) / max(1, sum(len(value) for value in sections.values() if isinstance(value, list))), 4),
    }
    body = {"schema_version": schema, "kind": kind, "sections": sections, "quality": quality}
    manifest_values = sections.get("sources", sections.get("evidence_anchors", []))
    body["source_manifest_sha256"] = _ca_sha(manifest_values)
    body, budget = _ca_budgeted(body, budget_tokens)
    body["budget"] = budget
    body["artifact_sha256"] = _ca_sha(body)
    return body


def build_agent_context_artifact(*, intent: str, constraints: Any = None, entities: Any = None, sources: Any = None, examples: Any = None, action_boundaries: Any = None, budget_tokens: int | None = None, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    sections = {
        "intent": _ca_text(intent, "intent"),
        "constraints": _ca_list(constraints, "constraints"),
        "entities": [_ca_entity(value, index) for index, value in enumerate((entities or [])[:32])],
        "sources": [_ca_source(value, index) for index, value in enumerate((sources or [])[:32])],
        "examples": _ca_list(examples, "examples"),
        "action_boundaries": _ca_list(action_boundaries, "action_boundaries"),
    }
    artifact = _ca_finalize(_CA_SCHEMA, "agent_context", sections, budget_tokens=budget_tokens)
    if metadata:
        artifact["metadata"] = {str(key): _ca_id(value, f"metadata.{key}") for key, value in metadata.items() if str(key) in {"project", "profile", "revision"} and value is not None}
        artifact["artifact_sha256"] = _ca_sha({key: value for key, value in artifact.items() if key != "artifact_sha256"})
    return artifact


def build_memento_artifact(*, objective: str, constraints: Any = None, unresolved_questions: Any = None, evidence_anchors: Any = None, next_steps: Any = None, budget_tokens: int | None = None) -> dict[str, Any]:
    sections = {
        "objective": _ca_text(objective, "objective"),
        "constraints": _ca_list(constraints, "constraints"),
        "unresolved_questions": _ca_list(unresolved_questions, "unresolved_questions"),
        "evidence_anchors": [_ca_id(value, "evidence_anchor") for value in (evidence_anchors or [])[:32]],
        "next_steps": _ca_list(next_steps, "next_steps"),
    }
    return _ca_finalize(_CA_MEMENTO_SCHEMA, "memento", sections, budget_tokens=budget_tokens)


def load_context_artifact(payload: Mapping[str, Any] | str) -> dict[str, Any]:
    """Load and verify a portable artifact or JSON serialization."""
    try:
        value = json.loads(payload) if isinstance(payload, str) else dict(payload)
    except (TypeError, ValueError) as exc:
        raise ContextArtifactError("artifact JSON is invalid") from exc
    if not isinstance(value, dict) or value.get("schema_version") not in {_CA_SCHEMA, _CA_MEMENTO_SCHEMA}:
        raise ContextArtifactError("unsupported context artifact schema")
    supplied = value.get("artifact_sha256")
    if not isinstance(supplied, str):
        raise ContextArtifactError("artifact_sha256 is required")
    unsigned = dict(value)
    unsigned.pop("artifact_sha256", None)
    if _ca_sha(unsigned) != supplied:
        raise ContextArtifactError("artifact commitment mismatch")
    return value


def verify_context_artifact(payload: Mapping[str, Any] | str) -> dict[str, Any]:
    artifact = load_context_artifact(payload)
    return {
        "valid": True,
        "schema_version": artifact["schema_version"],
        "kind": artifact.get("kind"),
        "artifact_sha256": artifact["artifact_sha256"],
        "source_manifest_sha256": artifact.get("source_manifest_sha256"),
        "budget": artifact.get("budget", {}),
    }


def render_context_artifact(artifact: Mapping[str, Any], *, format: str = "json") -> str:
    if not isinstance(artifact, Mapping) or not artifact.get("artifact_sha256"):
        raise ContextArtifactError("artifact must be finalized")
    mode = str(format).lower()
    if mode == "json":
        return json.dumps(dict(artifact), indent=2, sort_keys=True) + "\n"
    if mode in {"markdown", "md", "portable"}:
        lines = [f"# {artifact.get('kind', 'context artifact')}", "", f"Schema: `{artifact['schema_version']}`", f"Artifact: `{artifact['artifact_sha256']}`", ""]
        for key, value in artifact.get("sections", {}).items():
            lines.append(f"## {key.replace('_', ' ').title()}")
            if isinstance(value, list):
                lines.extend(f"- {json.dumps(item, sort_keys=True) if isinstance(item, dict) else item}" for item in value)
            else:
                lines.append(str(value))
            lines.append("")
        return "\n".join(lines)
    raise ContextArtifactError("format must be json, markdown, or portable")


def _ca_terms(text: str) -> list[str]:
    return sorted({token.lower() for token in _CA_TOKEN.findall(str(text or "")) if token.lower() not in _CA_STOP and len(token) > 1})


def train_context_cartridge(corpus: Mapping[str, str], *, corpus_id: str = "corpus") -> dict[str, Any]:
    if not isinstance(corpus, Mapping) or not corpus:
        raise ContextArtifactError("cartridge corpus must be a non-empty mapping")
    normalized_id = _ca_id(corpus_id, "corpus_id")
    hashes: dict[str, str] = {}
    entries: list[dict[str, Any]] = []
    for raw_id in sorted(corpus, key=str):
        source_id = _ca_id(raw_id, "source_id")
        text = corpus[raw_id]
        if not isinstance(text, str):
            raise ContextArtifactError("cartridge source content must be text")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        hashes[source_id] = digest
        entries.append({"source_id": source_id, "entity_sha256": digest, "term_hashes": sorted(hashlib.sha256(term.encode("utf-8")).hexdigest() for term in _ca_terms(text))})
    body = {
        "schema_version": _CA_CARTRIDGE_SCHEMA,
        "backend": "deterministic_hash_cartridge",
        "learned": False,
        "quality_status": "structural_only",
        "corpus_id": normalized_id,
        "model_compatibility": {
            "model_id": "none",
            "tokenizer_sha256": "none",
            "architecture": {"layers": 0, "heads": 0, "dtype": "none", "prefix_length": 0},
        },
        "source_entity_hashes": hashes,
        "entries": entries,
        "training": {"method": "offline self-study term projection", "synthetic_examples": len(entries) * 2, "raw_corpus_persisted": False},
    }
    body["cartridge_id"] = "cartridge:" + _ca_sha(body)[:32]
    body["cartridge_sha256"] = _ca_sha(body)
    return body


def load_context_cartridge(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("schema_version") != _CA_CARTRIDGE_SCHEMA or payload.get("backend") != "deterministic_hash_cartridge":
        raise ContextArtifactError("unsupported cartridge")
    if payload.get("learned") is not False or payload.get("quality_status") != "structural_only":
        raise ContextArtifactError("core loader only accepts explicitly structural cartridges")
    if not isinstance(payload.get("entries"), list) or not isinstance(payload.get("source_entity_hashes"), Mapping):
        raise ContextArtifactError("malformed cartridge")
    supplied = payload.get("cartridge_sha256")
    if not isinstance(supplied, str):
        raise ContextArtifactError("cartridge_sha256 is required")
    unsigned = dict(payload)
    unsigned.pop("cartridge_sha256", None)
    if _ca_sha(unsigned) != supplied:
        raise ContextArtifactError("cartridge commitment mismatch")
    return json.loads(_ca_json(payload))


def query_context_cartridge(cartridge: Mapping[str, Any], query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    loaded = load_context_cartridge(cartridge)
    query_hashes = {hashlib.sha256(term.encode("utf-8")).hexdigest() for term in _ca_terms(query)}
    scored = []
    for entry in loaded["entries"]:
        overlap = len(query_hashes.intersection(set(entry.get("term_hashes", []))))
        if overlap:
            scored.append({"source_id": entry["source_id"], "score": round(overlap / max(1, len(query_hashes)), 6), "evidence": {"source_entity_sha256": entry["entity_sha256"], "cartridge_id": loaded["cartridge_id"]}})
    scored.sort(key=lambda item: (-item["score"], item["source_id"]))
    return scored[: max(1, min(64, int(limit)))]


def compose_context_cartridges(cartridges: list[Mapping[str, Any]]) -> dict[str, Any]:
    loaded = [load_context_cartridge(item) for item in cartridges]
    if not loaded:
        raise ContextArtifactError("at least one cartridge is required")
    entries: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    ids = []
    for item in loaded:
        ids.append(item["cartridge_id"])
        hashes.update(item["source_entity_hashes"])
        for entry in item["entries"]:
            entries[entry["source_id"]] = entry
    compatibility = loaded[0].get("model_compatibility")
    if any(item.get("model_compatibility") != compatibility for item in loaded[1:]):
        raise ContextArtifactError("cartridges have incompatible model/tokenizer/shape metadata")
    body = {
        "schema_version": _CA_CARTRIDGE_SCHEMA,
        "backend": "deterministic_hash_cartridge",
        "learned": False,
        "quality_status": "structural_only",
        "corpus_id": "composed",
        "model_compatibility": compatibility,
        "cartridge_ids": sorted(ids),
        "source_entity_hashes": dict(sorted(hashes.items())),
        "entries": [entries[key] for key in sorted(entries)],
        "training": {"method": "composition", "raw_corpus_persisted": False},
    }
    body["cartridge_id"] = "cartridge:" + _ca_sha(body)[:32]
    body["cartridge_sha256"] = _ca_sha(body)
    return body


def evaluate_context_cartridge(corpus: Mapping[str, str], cartridge: Mapping[str, Any], queries: list[tuple[str, str]]) -> dict[str, Any]:
    loaded = load_context_cartridge(cartridge)
    full_bytes = sum(len(str(value).encode("utf-8")) for value in corpus.values())
    cartridge_bytes = len(_ca_json(loaded).encode("utf-8"))
    hits = query_context_cartridge(loaded, " ".join(query for query, _expected in queries), limit=64)
    found = {hit["source_id"] for hit in hits}
    expected = {expected for _query, expected in queries}
    return {"full_context_bytes": full_bytes, "cartridge_bytes": cartridge_bytes, "compression_ratio": round(full_bytes / max(1, cartridge_bytes), 4), "quality": round(len(found & expected) / max(1, len(expected)), 4), "throughput_proxy": round(len(queries) / max(1, cartridge_bytes), 8)}


def cmd_context_artifact(args, cfg) -> int:
    import json as _json
    from pathlib import Path
    try:
        payload = _json.loads(Path(args.input).read_text(encoding="utf-8"))
        kind = getattr(args, "kind", "structured")
        if kind == "memento":
            artifact = build_memento_artifact(**payload)
        else:
            artifact = build_agent_context_artifact(**payload)
        rendered = render_context_artifact(artifact, format=getattr(args, "format", "json"))
        output = getattr(args, "output", None)
        if output:
            Path(output).write_text(rendered, encoding="utf-8")
        if getattr(args, "json", False) or not output:
            print(rendered, end="")
        else:
            print(f"context-artifact -> {output}\nsha256: {artifact['artifact_sha256']}")
        return 0
    except (OSError, ValueError, ContextArtifactError) as exc:
        print(f"context-artifact: {exc}")
        return 1
