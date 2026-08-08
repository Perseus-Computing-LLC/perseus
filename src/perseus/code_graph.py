"""Optional local symbol/dependency code graph provider (#921)."""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from perseus.context_contract import context_rank

_CG_EXTENSIONS = frozenset({".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java", ".rb", ".c", ".cc", ".cpp", ".h", ".hpp", ".php", ".swift", ".kt", ".scala", ".sh"})
_CG_SYMBOL_RE = re.compile(r"^\s*(?:async\s+def|def|class|function|fn|func|type|struct|interface)\s+([A-Za-z_][A-Za-z0-9_]*)")
_CG_IMPORT_RE = re.compile(r"^\s*(?:from|import|use|require\s*\(|#include)\s+([^\s;,)]+)")
_CG_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_./:-]*")
_CG_STOP = frozenset({"a", "an", "and", "are", "be", "for", "from", "in", "is", "of", "on", "or", "the", "to", "use", "with"})


class CodeGraphError(ValueError):
    """Raised for invalid or unsafe code-graph requests."""


def _cg_sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _cg_terms(value: str) -> list[str]:
    return [token.lower() for token in _CG_TERM_RE.findall(str(value or "")) if token.lower() not in _CG_STOP]


def _cg_language(path: Path) -> str:
    return {".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript", ".rs": "rust", ".go": "go", ".java": "java", ".rb": "ruby", ".c": "c", ".cc": "cpp", ".cpp": "cpp", ".h": "c-header", ".hpp": "cpp-header", ".php": "php", ".swift": "swift", ".kt": "kotlin", ".scala": "scala", ".sh": "shell"}.get(path.suffix.lower(), "unknown")


def _cg_parse(path: Path, rel: str, text: str) -> dict[str, Any]:
    symbols: list[dict[str, Any]] = []
    imports: set[str] = set()
    calls: set[str] = set()
    parser = "lexical"
    if path.suffix.lower() == ".py":
        try:
            tree = ast.parse(text, filename=rel)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    symbols.append({"name": node.name, "kind": "class" if isinstance(node, ast.ClassDef) else "function", "line_start": int(node.lineno), "line_end": int(getattr(node, "end_lineno", node.lineno))})
                elif isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.add("." * int(node.level) + str(node.module or ""))
                elif isinstance(node, ast.Call):
                    fn = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                    if fn:
                        calls.add(fn)
            parser = "ast"
        except SyntaxError:
            # Fall through to the dependency-light lexical parser.
            symbols = []
    if not symbols:
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = _CG_SYMBOL_RE.match(line)
            if match:
                symbols.append({"name": match.group(1), "kind": "symbol", "line_start": lineno, "line_end": lineno})
    for line in text.splitlines():
        match = _CG_IMPORT_RE.match(line)
        if match:
            imports.add(match.group(1).strip("\"'"))
    sorted_symbols = sorted(symbols, key=lambda item: (item["line_start"], item["name"]))
    sorted_imports = sorted(imports)
    sorted_calls = sorted(calls)
    return {
        "path": rel, "language": _cg_language(path), "parser": parser, "degraded": parser != "ast" and path.suffix.lower() == ".py", "metadata_truncated": len(sorted_symbols) > 128 or len(sorted_imports) > 256 or len(sorted_calls) > 256, "sha256": _cg_sha_bytes(text.encode("utf-8", errors="replace")),
        "line_count": len(text.splitlines()), "bytes": len(text.encode("utf-8", errors="replace")),
        "symbols": sorted_symbols[:128],
        "imports": sorted_imports[:256], "calls": sorted_calls[:256],
    }


def _cg_candidate_cost(candidate: Mapping[str, Any]) -> int:
    return len(json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _cg_bound_candidate(candidate: dict[str, Any], *, rank: int, max_bytes: int) -> dict[str, Any] | None:
    bounded = json.loads(json.dumps(candidate, sort_keys=True))
    bounded["rank"] = int(rank)
    # Preserve the highest-signal symbol/edge prefix while making the provider
    # a hard byte-budget boundary rather than a best-effort hint.
    for width in (32, 16, 8, 4, 2, 1, 0):
        bounded["symbols"] = bounded.get("symbols", [])[:width]
        bounded["line_ranges"] = bounded.get("line_ranges", [])[:width]
        bounded["dependency_edges"] = bounded.get("dependency_edges", [])[:width]
        bounded["summary"] = str(bounded.get("summary", ""))[: max(32, width * 32)]
        bounded["agent_text"] = str(bounded.get("agent_text", ""))[: max(24, width * 24)]
        if _cg_candidate_cost(bounded) <= max_bytes:
            return bounded
    # If even the immutable identity cannot fit, abstain instead of returning
    # a candidate that violates the declared contract.
    return None


def _cg_workspace_hash(root: Path) -> str:
    return _cg_sha_bytes(str(root.resolve()).encode("utf-8"))


class CodeGraphIndex:
    """In-memory incremental index keyed by workspace and file content hashes."""

    def __init__(self, workspace: str | Path, *, max_files: int = 20_000) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        if not self.workspace.exists() or not self.workspace.is_dir():
            raise CodeGraphError("workspace must be an existing directory")
        self.max_files = max(1, min(100_000, int(max_files)))
        self._records: dict[str, dict[str, Any]] = {}
        self._last_fingerprint = ""

    def _files(self) -> list[Path]:
        result: list[Path] = []
        for path in self.workspace.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _CG_EXTENSIONS:
                continue
            rel_parts = path.relative_to(self.workspace).parts
            if any(part in {".git", ".perseus", ".venv", "__pycache__", "node_modules", "target"} for part in rel_parts):
                continue
            result.append(path)
        return sorted(result, key=lambda item: item.relative_to(self.workspace).as_posix())[: self.max_files]

    def refresh(self) -> dict[str, Any]:
        current: dict[str, str] = {}
        for path in self._files():
            rel = path.relative_to(self.workspace).as_posix()
            try:
                current[rel] = _cg_sha_bytes(path.read_bytes())
            except OSError:
                continue
        updated: list[str] = []
        reused: list[str] = []
        for rel in sorted(current):
            if rel in self._records and self._records[rel].get("sha256") == current[rel]:
                reused.append(rel)
                continue
            try:
                path = self.workspace / rel
                self._records[rel] = _cg_parse(path, rel, path.read_text(encoding="utf-8", errors="replace"))
                updated.append(rel)
            except OSError:
                self._records.pop(rel, None)
                continue
        removed = sorted(set(self._records) - set(current))
        for rel in removed:
            self._records.pop(rel, None)
        self._last_fingerprint = _cg_sha_bytes("".join(rel + current[rel] for rel in sorted(current)).encode("utf-8"))
        return {"workspace": str(self.workspace), "workspace_hash": _cg_workspace_hash(self.workspace), "fingerprint": self._last_fingerprint, "updated_files": updated, "reused_files": reused, "removed_files": removed, "file_count": len(self._records)}

    def records(self) -> list[dict[str, Any]]:
        if not self._last_fingerprint:
            self.refresh()
        return [json.loads(json.dumps(self._records[key], sort_keys=True)) for key in sorted(self._records)]

    def select(self, query: str, *, max_items: int = 12, max_bytes: int = 16_384, include_calls: bool = True) -> dict[str, Any]:
        query_text = str(query or "").strip()
        self.refresh()
        query_terms = _cg_terms(query_text)
        limit = max(1, min(64, int(max_items)))
        byte_limit = max(256, min(1_000_000, int(max_bytes)))
        scored: list[tuple[float, str, dict[str, Any], list[str]]] = []
        workspace_hash = _cg_workspace_hash(self.workspace)
        for rel, record in sorted(self._records.items()):
            path_terms = set(_cg_terms(rel))
            symbol_names = {str(item["name"]) for item in record["symbols"]}
            symbol_terms = set(_cg_terms(" ".join(symbol_names)))
            import_terms = set(_cg_terms(" ".join(record["imports"])))
            exact = [term for term in query_terms if term in symbol_names]
            overlap = len(set(query_terms) & (path_terms | symbol_terms | import_terms))
            score = len(exact) * 12.0 + overlap * 2.0
            if any(term in rel.lower() for term in query_terms):
                score += 3.0
            if score <= 0 and query_terms:
                continue
            reasons = []
            if exact:
                reasons.append("exact_symbol_match")
            if overlap:
                reasons.append("path_or_dependency_match")
            if not reasons:
                reasons.append("workspace_structure_match")
            edges = [{"type": "imports", "target": item} for item in record["imports"]]
            if include_calls:
                edges.extend({"type": "calls", "target": item} for item in record["calls"])
            candidate = {
                "candidate_id": "file:" + rel, "source_kind": "code_graph", "title": rel,
                "summary": rel + (" symbols: " + ", ".join(item["name"] for item in record["symbols"]) if record["symbols"] else ""),
                "agent_text": rel + " [" + ", ".join(item["name"] for item in record["symbols"]) + "]",
                "source_refs": ["file:" + rel], "content_sha256": record["sha256"], "workspace_hash": workspace_hash,
                "scope": {"workspace": workspace_hash}, "validity_state": "observed", "verified": True,
                "parser": record.get("parser", "lexical"), "degraded": bool(record.get("degraded", False)), "metadata_truncated": bool(record.get("metadata_truncated", False)),
                "symbols": record["symbols"], "line_ranges": [{"start": item["line_start"], "end": item["line_end"], "symbol": item["name"]} for item in record["symbols"]],
                "dependency_edges": edges, "bytes": record["bytes"], "selection_reason": "; ".join(reasons),
            }
            scored.append((score, rel, candidate, reasons))
        scored.sort(key=lambda item: (-item[0], item[1]))
        selected: list[dict[str, Any]] = []
        spent = 0
        for rank, (_score, _rel, candidate, _reasons) in enumerate(scored, start=1):
            if len(selected) >= limit:
                break
            bounded = _cg_bound_candidate(candidate, rank=rank, max_bytes=byte_limit)
            if bounded is None:
                continue
            cost = _cg_candidate_cost(bounded)
            if spent + cost > byte_limit:
                continue
            selected.append(bounded)
            spent += cost
        pipeline = context_rank(selected, task=query_text or "workspace structure", scope={"workspace": workspace_hash}, budget={"max_items": limit, "max_chars": byte_limit}, integrations={"vault": "not_configured", "ledger": "not_configured"}) if selected else {"status": "abstain", "candidates": []}
        return {"schema_version": "perseus-code-graph/v1", "workspace": str(self.workspace), "workspace_hash": workspace_hash, "fingerprint": self._last_fingerprint, "query": query_text, "candidates": selected, "bytes": spent, "budget_bytes": byte_limit, "context_pipeline": pipeline, "contribution": {"source_kind": "code_graph", "candidate_count": len(selected), "bytes": spent, "tokens_estimate": (spent + 3) // 4}}


def cmd_code_map(args, cfg) -> int:
    import json as _json
    workspace = Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    try:
        result = CodeGraphIndex(workspace).select(getattr(args, "query", "") or "", max_items=getattr(args, "limit", 12), max_bytes=getattr(args, "budget_bytes", 16_384), include_calls=getattr(args, "include_calls", False))
    except (OSError, CodeGraphError, ValueError) as exc:
        print(f"code-map: {exc}")
        return 1
    if getattr(args, "json", False):
        print(_json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"code-map: {result['workspace']} ({len(result['candidates'])} candidates)")
        for item in result["candidates"]:
            symbols = ", ".join(symbol["name"] for symbol in item.get("symbols", [])) or "(no symbols)"
            print(f"  {item['candidate_id']}  {symbols}  [{item['selection_reason']}]")
    return 0
