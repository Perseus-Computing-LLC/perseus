"""Strict, provider-free paired coding-agent utility protocol (#992).

This module is deliberately an offline protocol boundary.  It does not invoke a
model, discover credentials, run a verifier supplied by an agent, or publish
child-process output.  A future paid runner can use the contracts here only
after its own source, image, resource, identity, and spend-fence checks pass.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "perseus-agent-utility-preregistration/v1"
RESULT_SCHEMA_VERSION = "perseus-agent-utility-result/v1"
PUBLIC_EVIDENCE_SCHEMA_VERSION = "perseus-agent-utility-evidence/v1"
PROTOCOL_VERSION = "perseus-agent-utility/v1"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")
_FORBIDDEN_PUBLIC_PARTS = (
    "prompt", "query", "body", "content", "secret", "credential", "password",
    "passwd", "token", "api_key", "apikey", "authorization", "bearer",
    "stdout", "stderr", "host_path", "raw",
)


class ProtocolError(ValueError):
    """Base class for fail-closed protocol errors."""


class ManifestError(ProtocolError):
    """The preregistration is not a valid immutable challenge contract."""


class PreflightError(ProtocolError):
    """A run was attempted without a complete no-cost or spend preflight."""


class MutationAuditError(ProtocolError):
    """Workspace mutation evidence could not be established."""


class ResultValidationError(ProtocolError):
    """A result envelope violates the paired utility result contract."""


TOP_LEVEL_FIELDS = frozenset({
    "schema_version", "preregistration_id", "challenge", "source", "verifier",
    "fixtures", "arms", "resources", "model", "harness", "image", "limits",
    "stopping_rule", "spend_fence", "analysis", "manifest_digest",
})
CHALLENGE_FIELDS = frozenset({
    "id", "cohort_id", "visible_prompt", "prompt_digest", "task_digest",
    "fixture_digest", "allowed_output_subtrees", "toolchain_paths",
})
SOURCE_FIELDS = frozenset({
    "repository", "commit", "tree_digest", "materialization", "snapshot_path",
})
VERIFIER_FIELDS = frozenset({
    "id", "version", "digest", "owner", "hidden", "mutable", "path",
    "input_binding",
})
FIXTURE_FIELDS = frozenset({"id", "schema_version", "digest", "format", "path"})
ARM_FIELDS = frozenset({
    "id", "role", "memory_mode", "fixture_id", "fixture_digest",
    "credential_access", "integration_artifact", "instrumentation",
})
RESOURCE_FIELDS = frozenset({
    "cpu_millis", "memory_mb", "disk_mb", "timeout_seconds", "network",
})
MODEL_FIELDS = frozenset({"provider", "name", "version"})
HARNESS_FIELDS = frozenset({"id", "version", "digest"})
IMAGE_FIELDS = frozenset({"reference", "digest"})
LIMIT_FIELDS = frozenset({
    "max_turns", "max_cost_usd", "max_input_tokens", "max_output_tokens",
})
STOPPING_FIELDS = frozenset({"kind", "max_turns"})
SPEND_FIELDS = frozenset({
    "credential_identity", "per_key_budget_usd", "shared_headroom_usd",
    "required_between_arm_drain",
})
ANALYSIS_FIELDS = frozenset({
    "min_pairs", "continuous_metric_min_pairs", "cohort_policy", "paired_metrics",
})
RESULT_FIELDS = frozenset({
    "schema_version", "protocol_version", "run_id", "challenge_id", "manifest_digest",
    "comparability_key", "cases", "metrics", "build_under_test", "analysis",
    "accepted_count", "excluded_count", "paired_deltas", "report", "result_digest", "smoke",
})
CASE_FIELDS = frozenset({
    "case_id", "pair_id", "cohort_id", "challenge_id", "arm_id", "role", "status",
    "acceptance", "exclusion_reasons", "comparability_key", "capability", "delivery",
    "observable_use", "outcome",
})


def canonical_json(value: Any) -> str:
    """Return deterministic JSON and reject NaN/Infinity in digest inputs."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_value(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def _mapping(value: Any, field: str, exc: type[ProtocolError] = ManifestError) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise exc(f"{field} must be an object")
    return value


def _unknown(value: Mapping[str, Any], allowed: Iterable[str], field: str) -> None:
    extra = sorted(set(value) - set(allowed))
    if extra:
        raise ManifestError(f"{field} has unknown field(s): {', '.join(extra)}")


def _required(value: Mapping[str, Any], key: str, field: str) -> Any:
    if key not in value:
        raise ManifestError(f"{field}.{key} is required")
    return value[key]


def _text(value: Any, field: str, *, identifier: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{field} must be a non-empty string")
    text = value.strip()
    if any(ord(char) < 32 for char in text):
        raise ManifestError(f"{field} contains a control character")
    if identifier and not _ID.fullmatch(text):
        raise ManifestError(f"{field} is not a safe identifier")
    return text


def _digest(value: Any, field: str, *, commit: bool = False) -> str:
    text = _text(value, field).lower()
    pattern = _HEX40 if commit else _HEX64
    if not pattern.fullmatch(text):
        kind = "40" if commit else "64"
        raise ManifestError(f"{field} must be a lowercase {kind}-character SHA-256/commit digest")
    return text


def _finite_number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ManifestError(f"{field} must be finite")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ManifestError(f"{field} must be >= {minimum}")
    return number


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ManifestError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ManifestError(f"{field} must be a non-negative integer")
    return value


def _relative_path(value: Any, field: str) -> str:
    text = _text(value, field)
    path = text.replace("\\", "/")
    if path.startswith("/") or re.match(r"^[A-Za-z]:/", path) or "\x00" in path:
        raise ManifestError(f"{field} must be a relative path")
    parts = path.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ManifestError(f"{field} contains a path escape")
    return path


def _copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False))


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_entries(root: Path) -> dict[str, dict[str, Any]]:
    """Capture files, directories, symlinks, types, and permission bits without following links."""
    root = root.resolve()
    if not root.is_dir():
        raise MutationAuditError(f"workspace root is not a directory: {root.name}")
    entries: dict[str, dict[str, Any]] = {}

    def visit(directory: Path, relative: str = "") -> None:
        try:
            children = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise MutationAuditError("workspace could not be scanned") from exc
        for entry in children:
            rel = f"{relative}/{entry.name}" if relative else entry.name
            try:
                info = entry.stat(follow_symlinks=False)
                mode = stat.S_IMODE(info.st_mode)
                if stat.S_ISLNK(info.st_mode):
                    target = os.readlink(entry.path)
                    entries[rel] = {
                        "kind": "symlink", "mode": mode,
                        "target": target, "target_digest": sha256_bytes(target.encode()),
                    }
                elif stat.S_ISDIR(info.st_mode):
                    entries[rel] = {"kind": "directory", "mode": mode}
                    visit(Path(entry.path), rel)
                elif stat.S_ISREG(info.st_mode):
                    entries[rel] = {
                        "kind": "file", "mode": mode, "bytes": info.st_size,
                        "sha256": _digest_file(Path(entry.path)),
                    }
                else:
                    entries[rel] = {"kind": "other", "mode": mode}
            except OSError as exc:
                raise MutationAuditError("workspace entry could not be inspected") from exc

    visit(root)
    return entries


def snapshot_tree(root: str | os.PathLike[str] | Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return a deterministic tree snapshot; mappings are accepted for audit reuse."""
    if isinstance(root, Mapping):
        return _copy_json(root)
    return _snapshot_entries(Path(root))


def tree_digest(root: str | os.PathLike[str] | Mapping[str, Mapping[str, Any]]) -> str:
    """Digest portable source bytes/types; permission bits stay in mutation audits."""
    entries = snapshot_tree(root)
    portable = {
        path: {key: item for key, item in entry.items() if key != "mode"}
        for path, entry in entries.items()
    }
    return sha256_value({"entries": portable})


def _digest_path(path: Path) -> str:
    if path.is_dir() and not path.is_symlink():
        return tree_digest(path)
    if path.is_file() and not path.is_symlink():
        return _digest_file(path)
    raise ManifestError(f"fixture path is missing or unsupported: {path.name}")


def fixture_bundle_digest(fixtures: Mapping[str, Mapping[str, Any]]) -> str:
    return sha256_value({key: fixtures[key]["digest"] for key in sorted(fixtures)})


def _validate_fixture_map(fixtures: Any, *, base_dir: Path | None) -> dict[str, dict[str, Any]]:
    value = _mapping(fixtures, "fixtures")
    required = {"capability", "replay", "memory"}
    if set(value) != required:
        raise ManifestError("fixtures must contain exactly capability, replay, and memory")
    result: dict[str, dict[str, Any]] = {}
    for key in sorted(required):
        item = _mapping(value[key], f"fixtures.{key}")
        _unknown(item, FIXTURE_FIELDS, f"fixtures.{key}")
        for required_key in ("id", "schema_version", "digest", "format", "path"):
            _required(item, required_key, f"fixtures.{key}")
        item_id = _text(item["id"], f"fixtures.{key}.id", identifier=True)
        path = _relative_path(item["path"], f"fixtures.{key}.path")
        digest = _digest(item["digest"], f"fixtures.{key}.digest")
        if base_dir is not None:
            target = (base_dir / path).resolve()
            try:
                target.relative_to(base_dir.resolve())
            except ValueError as exc:
                raise ManifestError(f"fixtures.{key}.path escapes fixture root") from exc
            if not target.exists() or _digest_path(target) != digest:
                raise ManifestError(f"fixtures.{key}.digest does not match fixture bytes")
        result[key] = {
            "id": item_id, "schema_version": _text(item["schema_version"], f"fixtures.{key}.schema_version"),
            "digest": digest, "format": _text(item["format"], f"fixtures.{key}.format"), "path": path,
        }
    if len({item["id"] for item in result.values()}) != len(result):
        raise ManifestError("fixture ids must be unique")
    return result


def _validate_manifest_shape(manifest: Any, *, base_dir: Path | None) -> dict[str, Any]:
    value = _mapping(manifest, "manifest")
    _unknown(value, TOP_LEVEL_FIELDS, "manifest")
    for key in TOP_LEVEL_FIELDS - {"manifest_digest"}:
        _required(value, key, "manifest")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ManifestError(f"unsupported schema_version: {value.get('schema_version')!r}")
    _text(value["preregistration_id"], "manifest.preregistration_id", identifier=True)

    challenge = _mapping(value["challenge"], "challenge")
    _unknown(challenge, CHALLENGE_FIELDS, "challenge")
    for key in CHALLENGE_FIELDS:
        _required(challenge, key, "challenge")
    challenge_id = _text(challenge["id"], "challenge.id", identifier=True)
    cohort_id = _text(challenge["cohort_id"], "challenge.cohort_id", identifier=True)
    prompt = _text(challenge["visible_prompt"], "challenge.visible_prompt")
    prompt_digest = _digest(challenge["prompt_digest"], "challenge.prompt_digest")
    if prompt_digest != sha256_bytes(prompt.encode("utf-8")):
        raise ManifestError("challenge.prompt_digest does not bind visible_prompt")
    task_digest = _digest(challenge["task_digest"], "challenge.task_digest")
    fixture_digest = _digest(challenge["fixture_digest"], "challenge.fixture_digest")
    outputs = challenge["allowed_output_subtrees"]
    toolchain = challenge["toolchain_paths"]
    if not isinstance(outputs, list) or not outputs:
        raise ManifestError("challenge.allowed_output_subtrees must be non-empty")
    if not isinstance(toolchain, list):
        raise ManifestError("challenge.toolchain_paths must be a list")
    allowed_outputs = [_relative_path(item, "challenge.allowed_output_subtrees[]") for item in outputs]
    toolchain_paths = [_relative_path(item, "challenge.toolchain_paths[]") for item in toolchain]
    if len(set(allowed_outputs)) != len(allowed_outputs) or len(set(toolchain_paths)) != len(toolchain_paths):
        raise ManifestError("declared workspace paths must be unique")

    source = _mapping(value["source"], "source")
    _unknown(source, SOURCE_FIELDS, "source")
    for key in SOURCE_FIELDS:
        _required(source, key, "source")
    source_commit = _digest(source["commit"], "source.commit", commit=True)
    source_tree_digest = _digest(source["tree_digest"], "source.tree_digest")
    if source["materialization"] != "gitless":
        raise ManifestError("source.materialization must be gitless")
    snapshot_path = _relative_path(source["snapshot_path"], "source.snapshot_path")
    if base_dir is not None:
        target = (base_dir / snapshot_path).resolve()
        try:
            target.relative_to(base_dir.resolve())
        except ValueError as exc:
            raise ManifestError("source.snapshot_path escapes fixture root") from exc
        if not target.is_dir() or tree_digest(target) != source_tree_digest:
            raise ManifestError("source.tree_digest does not match the pinned source snapshot")
    source_norm = {
        "repository": _text(source["repository"], "source.repository"), "commit": source_commit,
        "tree_digest": source_tree_digest, "materialization": "gitless", "snapshot_path": snapshot_path,
    }

    verifier = _mapping(value["verifier"], "verifier")
    _unknown(verifier, VERIFIER_FIELDS, "verifier")
    for key in VERIFIER_FIELDS:
        _required(verifier, key, "verifier")
    verifier_norm = {
        "id": _text(verifier["id"], "verifier.id", identifier=True),
        "version": _text(verifier["version"], "verifier.version"),
        "digest": _digest(verifier["digest"], "verifier.digest"),
        "owner": verifier["owner"], "hidden": verifier["hidden"], "mutable": verifier["mutable"],
        "path": _relative_path(verifier["path"], "verifier.path"),
    }
    if verifier_norm["owner"] != "runner" or verifier_norm["hidden"] is not True or verifier_norm["mutable"] is not False:
        raise ManifestError("verifier must be hidden, immutable, and runner-owned")
    binding = _mapping(verifier["input_binding"], "verifier.input_binding")
    expected_binding_keys = {"challenge_id", "task_digest", "source_commit", "fixture_digest"}
    if set(binding) != expected_binding_keys:
        raise ManifestError("verifier.input_binding is incomplete or unbound")
    expected_binding = {
        "challenge_id": challenge_id, "task_digest": task_digest,
        "source_commit": source_commit, "fixture_digest": fixture_digest,
    }
    if dict(binding) != expected_binding:
        raise ManifestError("verifier.input_binding does not bind challenge, source, and fixture")
    verifier_norm["input_binding"] = expected_binding
    if base_dir is not None:
        target = (base_dir / verifier_norm["path"]).resolve()
        try:
            target.relative_to(base_dir.resolve())
        except ValueError as exc:
            raise ManifestError("verifier.path escapes fixture root") from exc
        if not target.is_file() or _digest_file(target) != verifier_norm["digest"]:
            raise ManifestError("verifier.digest does not match runner-owned verifier bytes")

    fixtures = _validate_fixture_map(value["fixtures"], base_dir=base_dir)
    if fixture_digest != fixture_bundle_digest(fixtures):
        raise ManifestError("challenge.fixture_digest does not bind capability/replay/memory fixtures")

    arms_raw = value["arms"]
    if not isinstance(arms_raw, list) or len(arms_raw) < 2:
        raise ManifestError("arms must contain at least control and treatment")
    arms: list[dict[str, Any]] = []
    arm_ids: set[str] = set()
    roles: list[str] = []
    allowed_roles = {"control", "treatment", "regular_recall", "instrumentation"}
    allowed_modes = {"source_only", "frozen_fixture", "regular_recall", "instrumented"}
    for index, raw in enumerate(arms_raw):
        item = _mapping(raw, f"arms[{index}]")
        _unknown(item, ARM_FIELDS, f"arms[{index}]")
        for key in ARM_FIELDS:
            _required(item, key, f"arms[{index}]")
        arm_id = _text(item["id"], f"arms[{index}].id", identifier=True)
        role = _text(item["role"], f"arms[{index}].role", identifier=True)
        mode = _text(item["memory_mode"], f"arms[{index}].memory_mode", identifier=True)
        if arm_id in arm_ids:
            raise ManifestError("arm ids must be unique")
        if role not in allowed_roles or mode not in allowed_modes:
            raise ManifestError("arm role or memory_mode is unsupported")
        if not isinstance(item["credential_access"], bool) or not isinstance(item["integration_artifact"], bool):
            raise ManifestError("arm credential_access and integration_artifact must be booleans")
        fixture_id = item["fixture_id"]
        fixture_digest_value = item["fixture_digest"]
        if fixture_id is not None:
            fixture_id = _text(fixture_id, f"arms[{index}].fixture_id", identifier=True)
        if fixture_digest_value is not None:
            fixture_digest_value = _digest(fixture_digest_value, f"arms[{index}].fixture_digest")
        if role == "control":
            if mode != "source_only" or fixture_id is not None or fixture_digest_value is not None:
                raise ManifestError("control arm must be source-only and fixture-free")
            if item["credential_access"] or item["integration_artifact"]:
                raise ManifestError("control arm cannot receive memory credentials or an integration artifact")
        elif role == "treatment":
            memory = fixtures["memory"]
            if mode != "frozen_fixture" or fixture_id != memory["id"] or fixture_digest_value != memory["digest"]:
                raise ManifestError("treatment arm must use the digest-pinned memory fixture")
        elif role == "regular_recall" and mode != "regular_recall":
            raise ManifestError("regular_recall arm must declare regular_recall memory_mode")
        elif role == "instrumentation" and mode != "instrumented":
            raise ManifestError("instrumentation arm must declare instrumented memory_mode")
        arm_ids.add(arm_id)
        roles.append(role)
        arms.append({
            "id": arm_id, "role": role, "memory_mode": mode, "fixture_id": fixture_id,
            "fixture_digest": fixture_digest_value, "credential_access": item["credential_access"],
            "integration_artifact": item["integration_artifact"], "instrumentation": _copy_json(item["instrumentation"]),
        })
    if roles.count("control") != 1 or roles.count("treatment") != 1:
        raise ManifestError("exactly one control and one treatment arm are required")

    resources = _mapping(value["resources"], "resources")
    _unknown(resources, RESOURCE_FIELDS, "resources")
    for key in RESOURCE_FIELDS:
        _required(resources, key, "resources")
    resources_norm = {
        "cpu_millis": _positive_int(resources["cpu_millis"], "resources.cpu_millis"),
        "memory_mb": _positive_int(resources["memory_mb"], "resources.memory_mb"),
        "disk_mb": _positive_int(resources["disk_mb"], "resources.disk_mb"),
        "timeout_seconds": _finite_number(resources["timeout_seconds"], "resources.timeout_seconds", minimum=0.001),
        "network": _text(resources["network"], "resources.network", identifier=True),
    }
    if resources_norm["network"] not in {"disabled", "allowlisted"}:
        raise ManifestError("resources.network must be disabled or allowlisted")

    model = _mapping(value["model"], "model")
    _unknown(model, MODEL_FIELDS, "model")
    for key in MODEL_FIELDS:
        _required(model, key, "model")
    model_norm = {key: _text(model[key], f"model.{key}") for key in MODEL_FIELDS}
    harness = _mapping(value["harness"], "harness")
    _unknown(harness, HARNESS_FIELDS, "harness")
    for key in HARNESS_FIELDS:
        _required(harness, key, "harness")
    harness_norm = {"id": _text(harness["id"], "harness.id", identifier=True), "version": _text(harness["version"], "harness.version"), "digest": _digest(harness["digest"], "harness.digest")}
    image = _mapping(value["image"], "image")
    _unknown(image, IMAGE_FIELDS, "image")
    for key in IMAGE_FIELDS:
        _required(image, key, "image")
    image_norm = {"reference": _text(image["reference"], "image.reference"), "digest": _digest(image["digest"], "image.digest")}

    limits = _mapping(value["limits"], "limits")
    _unknown(limits, LIMIT_FIELDS, "limits")
    for key in LIMIT_FIELDS:
        _required(limits, key, "limits")
    limits_norm = {
        "max_turns": _positive_int(limits["max_turns"], "limits.max_turns"),
        "max_cost_usd": _finite_number(limits["max_cost_usd"], "limits.max_cost_usd", minimum=0),
        "max_input_tokens": _positive_int(limits["max_input_tokens"], "limits.max_input_tokens"),
        "max_output_tokens": _positive_int(limits["max_output_tokens"], "limits.max_output_tokens"),
    }
    stopping = _mapping(value["stopping_rule"], "stopping_rule")
    _unknown(stopping, STOPPING_FIELDS, "stopping_rule")
    for key in STOPPING_FIELDS:
        _required(stopping, key, "stopping_rule")
    if stopping["kind"] != "verifier_pass_or_limit" or stopping["max_turns"] != limits_norm["max_turns"]:
        raise ManifestError("stopping_rule contradicts limits")
    stopping_norm = {"kind": "verifier_pass_or_limit", "max_turns": limits_norm["max_turns"]}

    spend = _mapping(value["spend_fence"], "spend_fence")
    _unknown(spend, SPEND_FIELDS, "spend_fence")
    for key in SPEND_FIELDS:
        _required(spend, key, "spend_fence")
    identity = _text(spend["credential_identity"], "spend_fence.credential_identity", identifier=True)
    if any(part in identity.lower() for part in ("token", "secret", "key=", "ghp_")):
        raise ManifestError("spend_fence.credential_identity must be a non-secret identity label")
    spend_norm = {
        "credential_identity": identity,
        "per_key_budget_usd": _finite_number(spend["per_key_budget_usd"], "spend_fence.per_key_budget_usd", minimum=0),
        "shared_headroom_usd": _finite_number(spend["shared_headroom_usd"], "spend_fence.shared_headroom_usd", minimum=0),
        "required_between_arm_drain": spend["required_between_arm_drain"],
    }
    if spend_norm["required_between_arm_drain"] is not True:
        raise ManifestError("spend fence must require observed between-arm drain")

    analysis = _mapping(value["analysis"], "analysis")
    _unknown(analysis, ANALYSIS_FIELDS, "analysis")
    for key in ANALYSIS_FIELDS:
        _required(analysis, key, "analysis")
    paired_metrics = analysis["paired_metrics"]
    if not isinstance(paired_metrics, list) or not paired_metrics or not all(isinstance(item, str) and item for item in paired_metrics):
        raise ManifestError("analysis.paired_metrics must be non-empty")
    analysis_norm = {
        "min_pairs": _positive_int(analysis["min_pairs"], "analysis.min_pairs"),
        "continuous_metric_min_pairs": _positive_int(analysis["continuous_metric_min_pairs"], "analysis.continuous_metric_min_pairs"),
        "cohort_policy": analysis["cohort_policy"], "paired_metrics": list(paired_metrics),
    }
    if analysis_norm["cohort_policy"] != "separate_no_pooling":
        raise ManifestError("analysis.cohort_policy must be separate_no_pooling")
    if analysis_norm["continuous_metric_min_pairs"] < analysis_norm["min_pairs"]:
        raise ManifestError("continuous metric minimum cannot be below minimum paired sample")

    normalized = {
        "schema_version": SCHEMA_VERSION,
        "preregistration_id": _text(value["preregistration_id"], "manifest.preregistration_id", identifier=True),
        "challenge": {
            "id": challenge_id, "cohort_id": cohort_id, "visible_prompt": prompt,
            "prompt_digest": prompt_digest, "task_digest": task_digest, "fixture_digest": fixture_digest,
            "allowed_output_subtrees": allowed_outputs, "toolchain_paths": toolchain_paths,
        },
        "source": source_norm, "verifier": verifier_norm, "fixtures": fixtures, "arms": arms,
        "resources": resources_norm, "model": model_norm, "harness": harness_norm, "image": image_norm,
        "limits": limits_norm, "stopping_rule": stopping_norm, "spend_fence": spend_norm,
        "analysis": analysis_norm,
    }
    return normalized


def seal_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize and add the self-excluding manifest digest."""
    raw = _copy_json(manifest)
    raw.pop("manifest_digest", None)
    normalized = _validate_manifest_shape(raw, base_dir=None)
    normalized["manifest_digest"] = sha256_value(normalized)
    return normalized


def validate_manifest(manifest: Any, *, base_dir: str | os.PathLike[str] | None = None, require_seal: bool = True) -> dict[str, Any]:
    """Validate a manifest strictly, including optional fixture bytes and its seal."""
    normalized = _validate_manifest_shape(manifest, base_dir=Path(base_dir).resolve() if base_dir else None)
    provided = manifest.get("manifest_digest") if isinstance(manifest, Mapping) else None
    if require_seal:
        if not isinstance(provided, str) or not _HEX64.fullmatch(provided):
            raise ManifestError("manifest.manifest_digest is required")
        if provided != sha256_value(normalized):
            raise ManifestError("manifest_digest does not match the immutable manifest")
        normalized["manifest_digest"] = provided
    return normalized


def load_manifest(path: str | os.PathLike[str]) -> dict[str, Any]:
    target = Path(path).resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("manifest is not readable JSON") from exc
    return validate_manifest(value, base_dir=target.parent)


def fixture_runtime(manifest: Mapping[str, Any], base_dir: str | os.PathLike[str]) -> dict[str, Any]:
    value = validate_manifest(manifest, base_dir=base_dir)
    return {
        "challenge_id": value["challenge"]["id"],
        "task_digest": value["challenge"]["task_digest"],
        "fixture_digest": value["challenge"]["fixture_digest"],
        "manifest_digest": value["manifest_digest"],
        "source_commit": value["source"]["commit"],
        "source_tree_digest": value["source"]["tree_digest"],
        "verifier_digest": value["verifier"]["digest"],
        "verifier_id": value["verifier"]["id"],
        "fixture_digests": {key: item["digest"] for key, item in value["fixtures"].items()},
        "model": value["model"],
        "harness": value["harness"],
        "harness_digest": value["harness"]["digest"],
        "image_digest": value["image"]["digest"],
        "resource_envelope": value["resources"],
    }


def _compare_runtime(manifest: Mapping[str, Any], runtime: Mapping[str, Any] | None) -> list[str]:
    failed: list[str] = []
    if not isinstance(runtime, Mapping):
        return [
            "source_preflight_missing", "challenge_preflight_missing", "verifier_preflight_missing",
            "fixture_preflight_missing", "model_preflight_missing", "harness_preflight_missing",
            "image_preflight_missing", "resource_preflight_missing",
        ]
    challenge = manifest["challenge"]
    source = manifest["source"]
    if runtime.get("source_commit") != source["commit"] or runtime.get("source_tree_digest") != source["tree_digest"]:
        failed.append("source_mismatch")
    if runtime.get("challenge_id") != challenge["id"] or runtime.get("task_digest") != challenge["task_digest"]:
        failed.append("challenge_mismatch")
    if runtime.get("manifest_digest") != manifest["manifest_digest"]:
        failed.append("challenge_mismatch")
    if runtime.get("fixture_digest") != challenge["fixture_digest"]:
        failed.append("fixture_mismatch")
    expected_fixture_digests = {key: item["digest"] for key, item in manifest["fixtures"].items()}
    if runtime.get("fixture_digests") != expected_fixture_digests:
        failed.append("fixture_mismatch")
    if runtime.get("verifier_digest") != manifest["verifier"]["digest"]:
        failed.append("verifier_mismatch")
    if runtime.get("verifier_id") != manifest["verifier"]["id"]:
        failed.append("verifier_mismatch")
    if "model" not in runtime:
        failed.append("model_preflight_missing")
    elif runtime.get("model") != manifest["model"]:
        failed.append("model_mismatch")
    if "harness" not in runtime:
        failed.append("harness_preflight_missing")
    elif runtime.get("harness") != manifest["harness"]:
        failed.append("harness_mismatch")
    if runtime.get("harness_digest") != manifest["harness"]["digest"]:
        failed.append("harness_mismatch")
    if "image_digest" not in runtime:
        failed.append("image_preflight_missing")
    elif runtime.get("image_digest") != manifest["image"]["digest"]:
        failed.append("image_mismatch")
    if "resource_envelope" not in runtime:
        failed.append("resource_preflight_missing")
    elif runtime.get("resource_envelope") != manifest["resources"]:
        failed.append("resource_mismatch")
    return sorted(set(failed))


def run_preflight(
    manifest: Mapping[str, Any] | str | os.PathLike[str],
    *,
    runtime: Mapping[str, Any] | None = None,
    paid: bool = False,
    credential_identity: str | None = None,
    spend: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run no-cost identity gates; paid mode additionally requires observed spend fencing."""
    value = load_manifest(manifest) if isinstance(manifest, (str, os.PathLike)) else validate_manifest(manifest)
    failed = _compare_runtime(value, runtime)
    checks = {
        "source": "source_mismatch" not in failed and "source_preflight_missing" not in failed,
        "challenge": "challenge_mismatch" not in failed and "challenge_preflight_missing" not in failed,
        "verifier": "verifier_mismatch" not in failed and "verifier_preflight_missing" not in failed,
        "fixture": "fixture_mismatch" not in failed and "fixture_preflight_missing" not in failed,
        "harness": "harness_mismatch" not in failed and "harness_preflight_missing" not in failed,
        "image": "image_mismatch" not in failed and "image_preflight_missing" not in failed,
        "resources": "resource_mismatch" not in failed and "resource_preflight_missing" not in failed,
    }
    spend_receipt: dict[str, Any]
    if not paid:
        spend_receipt = {"status": "not_run", "reason": "offline no-cost preflight"}
    else:
        if credential_identity is None:
            failed.append("credential_identity_missing")
        elif credential_identity != value["spend_fence"]["credential_identity"]:
            failed.append("credential_identity_mismatch")
        if spend is None:
            failed.append("spend_check_missing")
            spend_receipt = {"status": "failed", "reason": "spend fence was not observed"}
        else:
            expected = value["spend_fence"]
            spend_receipt = {
                "status": "passed", "credential_identity": expected["credential_identity"],
                "between_arm_drain_observed": spend.get("between_arm_drain_observed"),
            }
            if spend.get("credential_identity") != expected["credential_identity"]:
                failed.append("spend_identity_mismatch")
            for key in ("per_key_budget_usd", "shared_headroom_usd"):
                if spend.get(key) != expected[key]:
                    failed.append(f"spend_{key}_mismatch")
            if spend.get("between_arm_drain_observed") is not True:
                failed.append("between_arm_drain_unobserved")
            if spend.get("required_between_arm_drain") is not expected["required_between_arm_drain"]:
                failed.append("spend_requirement_mismatch")
            if failed:
                spend_receipt["status"] = "failed"
    return {
        "status": "passed" if not failed else "blocked",
        "ready": not failed,
        "paid": paid,
        "failed": sorted(set(failed)),
        "checks": checks,
        "spend": spend_receipt,
        "model_calls": 0,
    }


def assert_paid_preflight(*args: Any, **kwargs: Any) -> dict[str, Any]:
    kwargs["paid"] = True
    result = run_preflight(*args, **kwargs)
    if not result["ready"]:
        raise PreflightError("paid utility run blocked: " + ", ".join(result["failed"]))
    return result


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        raise ProtocolError("destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True)


def materialize_gitless_project(source_root: str | os.PathLike[str], destination: str | os.PathLike[str], source: Mapping[str, Any]) -> dict[str, Any]:
    source_path = Path(source_root).resolve()
    destination_path = Path(destination).resolve()
    if (source_path / ".git").exists():
        raise ProtocolError("source snapshot must be materialized without .git")
    expected = _digest(source["tree_digest"], "source.tree_digest")
    if tree_digest(source_path) != expected:
        raise ProtocolError("source snapshot digest mismatch")
    _copy_tree(source_path, destination_path)
    if (destination_path / ".git").exists() or tree_digest(destination_path) != expected:
        raise ProtocolError("git-less source materialization verification failed")
    return {"status": "materialized", "source_commit": source["commit"], "tree_digest": expected, "gitless": True}


def restore_fixture(fixture_root: str | os.PathLike[str], destination: str | os.PathLike[str], fixture: Mapping[str, Any]) -> dict[str, Any]:
    source = (Path(fixture_root).resolve() / _relative_path(fixture["path"], "fixture.path")).resolve()
    base = Path(fixture_root).resolve()
    try:
        source.relative_to(base)
    except ValueError as exc:
        raise ProtocolError("fixture path escapes fixture root") from exc
    if _digest_path(source) != fixture["digest"]:
        raise ProtocolError("fixture bytes do not match its digest")
    target = Path(destination).resolve()
    if source.is_dir() and not source.is_symlink():
        _copy_tree(source, target)
    else:
        if target.exists():
            raise ProtocolError("fixture destination already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    if _digest_path(target) != fixture["digest"]:
        raise ProtocolError("restored fixture digest mismatch")
    return {"status": "restored", "fixture_id": fixture["id"], "fixture_digest": fixture["digest"], "observed": True}


def _allowed_path(path: str, allowed: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(normalized == root or normalized.startswith(root + "/") for root in allowed)


def _mutation_kind(path: str, before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> str:
    if before is None:
        return "added"
    if after is None:
        return "removed"
    if before.get("kind") != after.get("kind"):
        return "type_changed"
    if before.get("kind") == "symlink" and before.get("target") != after.get("target"):
        return "symlink_retargeted"
    if before.get("kind") == "file" and before.get("sha256") != after.get("sha256"):
        return "changed"
    if before.get("mode") != after.get("mode"):
        return "permission"
    return "changed"


def audit_mutations(
    before: str | os.PathLike[str] | Mapping[str, Mapping[str, Any]],
    after: str | os.PathLike[str] | Mapping[str, Mapping[str, Any]],
    *,
    allowed_output_subtrees: Iterable[str] = (),
    toolchain_paths: Iterable[str] = (),
) -> dict[str, Any]:
    """Compare two trees and invalidate every mutation outside declared subtrees."""
    before_snapshot = snapshot_tree(before)
    after_snapshot = snapshot_tree(after)
    allowed = tuple(sorted(set(allowed_output_subtrees) | set(toolchain_paths)))
    all_paths = sorted(set(before_snapshot) | set(after_snapshot))
    mutations: list[dict[str, Any]] = []
    for path in all_paths:
        old = before_snapshot.get(path)
        new = after_snapshot.get(path)
        if old == new:
            continue
        kind = _mutation_kind(path, old, new)
        item = {"path": path, "kind": kind, "allowed": _allowed_path(path, allowed)}
        mutations.append(item)
    off_target = [item for item in mutations if not item["allowed"]]
    return {
        "valid": not off_target,
        "off_target": off_target,
        "mutations": mutations,
        "counts": {"total": len(mutations), "off_target": len(off_target)},
        "allowed_subtrees": list(allowed),
    }


# Explicit aliases make the audit boundary easy for adapters to discover.
mutation_audit = audit_mutations
workspace_mutation_audit = audit_mutations


def _run_id(value: Any) -> str:
    text = _text(value, "run_id", identifier=True)
    return text


def make_delivery_receipt(
    run_id: str, arm_id: str, *, delivered: bool, fixture_id: str | None = None,
    fixture_digest: str | None = None, status: str | None = None,
) -> dict[str, Any]:
    if fixture_digest is not None:
        fixture_digest = _digest(fixture_digest, "fixture_digest")
    if delivered and fixture_id is None:
        raise ProtocolError("delivered receipt needs a fixture id")
    return {
        "kind": "delivery", "run_id": _run_id(run_id), "arm_id": _text(arm_id, "arm_id", identifier=True),
        "status": status or ("delivered" if delivered else "source_only"), "delivered": bool(delivered),
        "fixture_id": fixture_id, "fixture_digest": fixture_digest,
    }


def make_observable_use_receipt(
    run_id: str, arm_id: str, *, marker_observed: bool | None, evidence_status: str | None = None,
) -> dict[str, Any]:
    observed = marker_observed is True
    return {
        "kind": "observable_use", "run_id": _run_id(run_id), "arm_id": _text(arm_id, "arm_id", identifier=True),
        "status": "observed" if observed else "not_observed",
        "evidence_status": evidence_status or ("marker_observed" if observed else "marker_absent_or_missing"),
        "marker_observed": marker_observed,
        "lower_bound": 1 if observed else 0,
        "non_use_inferred": False,
    }


def _measure(value: Any, field: str, *, missing_reason: str = "not_measured") -> dict[str, Any]:
    if value is None:
        return {"value": None, "missing": True, "missing_reason": missing_reason}
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ProtocolError(f"{field} must be finite or explicitly missing")
    return {"value": value, "missing": False, "missing_reason": None}


def make_outcome_receipt(
    run_id: str, arm_id: str, *, correctness: float | None,
    mutation_audit: Mapping[str, Any], calls: int | None = None, time_ms: float | None = None,
    input_tokens: int | None = None, output_tokens: int | None = None, cost_usd: float | None = None,
) -> dict[str, Any]:
    audit = _mapping(mutation_audit, "mutation_audit", ProtocolError)
    if not isinstance(audit.get("valid"), bool) or not isinstance(audit.get("off_target"), list):
        raise ProtocolError("outcome mutation_audit must be complete")
    invalidated = audit["valid"] is False
    score = _measure(0.0 if invalidated else correctness, "correctness", missing_reason="verifier_unavailable")
    if score["value"] is not None and not 0.0 <= float(score["value"]) <= 1.0:
        raise ProtocolError("correctness must be between 0 and 1")
    for name, value in (("calls", calls), ("time_ms", time_ms), ("input_tokens", input_tokens), ("output_tokens", output_tokens), ("cost_usd", cost_usd)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0):
            raise ProtocolError(f"{name} must be a non-negative finite measure")
    return {
        "kind": "outcome", "run_id": _run_id(run_id), "arm_id": _text(arm_id, "arm_id", identifier=True),
        "status": "invalidated" if invalidated else "completed", "correctness": score,
        "mutation_invalidated": invalidated,
        "workspace": {"mutation_audit": _copy_json(audit)},
        "usage": {
            "calls": _measure(calls, "calls"), "time_ms": _measure(time_ms, "time_ms"),
            "input_tokens": _measure(input_tokens, "input_tokens"), "output_tokens": _measure(output_tokens, "output_tokens"),
            "cost_usd": _measure(cost_usd, "cost_usd"),
        },
    }


def build_comparability_key(manifest: Mapping[str, Any]) -> str:
    value = validate_manifest(manifest)
    conditions = []
    for arm in sorted(value["arms"], key=lambda item: item["id"]):
        conditions.append({
            "id": arm["id"], "role": arm["role"], "memory_mode": arm["memory_mode"],
            "fixture_id": arm["fixture_id"], "fixture_digest": arm["fixture_digest"],
        })
    binding = {
        "challenge_id": value["challenge"]["id"], "fixture_digest": value["challenge"]["fixture_digest"],
        "model": value["model"], "conditions": conditions, "manifest_digest": value["manifest_digest"],
        "verifier_digest": value["verifier"]["digest"], "harness": value["harness"], "image": value["image"],
        "resources": value["resources"], "source_commit": value["source"]["commit"],
    }
    return sha256_value(binding)


def _case_ids(result: Mapping[str, Any]) -> set[str]:
    return {str(case.get("case_id")) for case in result.get("cases", []) if isinstance(case, Mapping)}


def derive_paired_deltas(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    cases = [case for case in result.get("cases", []) if isinstance(case, Mapping) and case.get("acceptance") == "accepted" and case.get("status") == "completed"]
    by_cohort: dict[str, dict[str, dict[str, Mapping[str, Any]]]] = {}
    for case in cases:
        pair = str(case.get("pair_id", ""))
        cohort = str(case.get("cohort_id", ""))
        role = str(case.get("role", ""))
        by_cohort.setdefault(cohort, {}).setdefault(pair, {})[role] = case
    minimum = int(result.get("analysis", {}).get("min_pairs", 1)) if isinstance(result.get("analysis"), Mapping) else 1
    output: list[dict[str, Any]] = []
    for cohort in sorted(by_cohort):
        pairs: list[dict[str, Any]] = []
        for pair_id in sorted(by_cohort[cohort]):
            arms = by_cohort[cohort][pair_id]
            if "control" not in arms or "treatment" not in arms:
                continue
            control_score = arms["control"].get("outcome", {}).get("correctness", {}).get("value")
            treatment_score = arms["treatment"].get("outcome", {}).get("correctness", {}).get("value")
            if not all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in (control_score, treatment_score)):
                continue
            pairs.append({"pair_id": pair_id, "control": control_score, "treatment": treatment_score, "delta": treatment_score - control_score})
        if not pairs:
            continue
        mean = sum(float(item["delta"]) for item in pairs) / len(pairs)
        output.append({
            "cohort_id": cohort, "metric_id": "correctness", "n_pairs": len(pairs), "pairs": pairs,
            "mean_delta": mean, "exploratory": len(pairs) < minimum,
            "significance": "not_run_below_preregistered_minimum" if len(pairs) < minimum else "not_run_in_offline_fixture",
        })
    return output


def build_result(
    manifest: Mapping[str, Any], cases: list[Mapping[str, Any]], metrics: list[Mapping[str, Any]],
    *, build_under_test: Mapping[str, Any], run_id: str = "synthetic-run-0001",
) -> dict[str, Any]:
    value = validate_manifest(manifest)
    key = build_comparability_key(value)
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION, "protocol_version": PROTOCOL_VERSION,
        "run_id": _run_id(run_id), "challenge_id": value["challenge"]["id"],
        "manifest_digest": value["manifest_digest"], "comparability_key": key,
        "cases": _copy_json(cases), "metrics": _copy_json(metrics),
        "build_under_test": _copy_json(build_under_test), "analysis": value["analysis"],
    }
    for case in result["cases"]:
        case.setdefault("comparability_key", key)
        role = next((arm["role"] for arm in value["arms"] if arm["id"] == case.get("arm_id")), None)
        case.setdefault("role", role)
    result["accepted_count"] = sum(case.get("acceptance") == "accepted" for case in result["cases"])
    result["excluded_count"] = sum(case.get("acceptance") == "excluded" for case in result["cases"])
    result["paired_deltas"] = derive_paired_deltas(result)
    result["report"] = {
        "observed": {"case_count": len(result["cases"]), "metric_count": len(result["metrics"])},
        "derived_paired_deltas": result["paired_deltas"],
        "exploratory": [item["cohort_id"] for item in result["paired_deltas"] if item["exploratory"]],
        "claims_not_established": [
            "This offline synthetic run does not establish memory efficacy, productivity, win-rate, or significance.",
            "Heterogeneous cohorts are not pooled into a single productivity score.",
        ],
    }
    result["result_digest"] = sha256_value(result)
    return result


def _validate_measure(value: Any, field: str) -> None:
    item = _mapping(value, field, ResultValidationError)
    if set(item) != {"value", "missing", "missing_reason"}:
        raise ResultValidationError(f"{field} has incomplete missingness contract")
    if not isinstance(item["missing"], bool):
        raise ResultValidationError(f"{field}.missing must be boolean")
    if item["missing"]:
        if not isinstance(item["missing_reason"], str) or not item["missing_reason"]:
            raise ResultValidationError(f"{field} needs a missing_reason")
        if item["value"] is not None:
            raise ResultValidationError(f"{field} cannot carry a value when missing")
    else:
        if item["missing_reason"] is not None or isinstance(item["value"], bool) or not isinstance(item["value"], (int, float)) or not math.isfinite(float(item["value"])):
            raise ResultValidationError(f"{field} must carry a finite value or explicit missingness")


def validate_result(result: Any, manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    value = _mapping(result, "result", ResultValidationError)
    unknown = sorted(set(value) - RESULT_FIELDS)
    if unknown:
        raise ResultValidationError("result has unknown field(s): " + ", ".join(unknown))
    for field in ("schema_version", "protocol_version", "run_id", "challenge_id", "manifest_digest", "comparability_key", "cases", "metrics", "build_under_test", "analysis", "accepted_count", "excluded_count", "paired_deltas", "report", "result_digest"):
        if field not in value:
            raise ResultValidationError(f"result.{field} is required")
    if value["schema_version"] != RESULT_SCHEMA_VERSION:
        raise ResultValidationError("unsupported result schema_version")
    if not isinstance(value["cases"], list) or not value["cases"]:
        raise ResultValidationError("result cases must be non-empty")
    if not isinstance(value["metrics"], list) or not value["metrics"]:
        raise ResultValidationError("result metrics must be non-empty")
    _digest(value["manifest_digest"], "result.manifest_digest")
    _digest(value["comparability_key"], "result.comparability_key")
    build = _mapping(value["build_under_test"], "result.build_under_test", ResultValidationError)
    if set(build) != {"id", "commit", "digest"}:
        raise ResultValidationError("build_under_test must be separately identified")
    if not isinstance(build["id"], str) or not build["id"] or not _HEX40.fullmatch(str(build["commit"])) or not _HEX64.fullmatch(str(build["digest"])):
        raise ResultValidationError("build_under_test identity or digest is invalid")
    if manifest is not None:
        expected_manifest = validate_manifest(manifest)
        if value["challenge_id"] != expected_manifest["challenge"]["id"] or value["manifest_digest"] != expected_manifest["manifest_digest"]:
            raise ResultValidationError("result is bound to a different challenge manifest")
        expected_key = build_comparability_key(expected_manifest)
        if value["comparability_key"] != expected_key:
            raise ResultValidationError("comparability key is not bound to challenge, both arms, and resources")
        arm_map = {arm["id"]: arm for arm in expected_manifest["arms"]}
    else:
        arm_map = {}

    pair_groups: dict[str, set[str]] = {}
    seen_cases: set[str] = set()
    for index, raw_case in enumerate(value["cases"]):
        case = _mapping(raw_case, f"result.cases[{index}]", ResultValidationError)
        unknown_case = sorted(set(case) - CASE_FIELDS)
        if unknown_case:
            raise ResultValidationError(f"case {index} has unknown field(s): {', '.join(unknown_case)}")
        for field in ("case_id", "pair_id", "cohort_id", "challenge_id", "arm_id", "role", "status", "acceptance", "comparability_key", "capability", "delivery", "observable_use", "outcome"):
            if field not in case:
                raise ResultValidationError(f"case {index} missing {field}")
        case_id = str(case["case_id"])
        if case_id in seen_cases:
            raise ResultValidationError("case ids must be unique")
        seen_cases.add(case_id)
        if case["status"] not in {"completed", "failed", "cancelled", "invalidated", "excluded"}:
            raise ResultValidationError("case status is invalid")
        if case["acceptance"] not in {"accepted", "excluded"}:
            raise ResultValidationError("case acceptance is invalid")
        if case["acceptance"] == "accepted" and case["status"] != "completed":
            raise ResultValidationError("only completed cases may be accepted")
        if case["acceptance"] == "excluded":
            reasons = case.get("exclusion_reasons")
            if not isinstance(reasons, list) or not reasons or not all(isinstance(reason, str) and reason for reason in reasons):
                raise ResultValidationError("excluded cases require exclusion reasons")
        elif case.get("exclusion_reasons"):
            raise ResultValidationError("accepted cases cannot carry exclusion reasons")
        if case["comparability_key"] != value["comparability_key"]:
            raise ResultValidationError("paired identity mismatch")
        if arm_map:
            arm = arm_map.get(case["arm_id"])
            if arm is None or case["role"] != arm["role"]:
                raise ResultValidationError("case arm is not in the manifest")
        capability = _mapping(case["capability"], f"case {index}.capability", ResultValidationError)
        status = capability.get("status")
        if status not in {"available", "partial", "unavailable", "not_applicable"}:
            raise ResultValidationError("case capability status must be explicit")
        if status in {"partial", "unavailable"} and not isinstance(capability.get("reason"), str):
            raise ResultValidationError("degraded capability needs a reason")
        delivery = _mapping(case["delivery"], f"case {index}.delivery", ResultValidationError)
        use = _mapping(case["observable_use"], f"case {index}.observable_use", ResultValidationError)
        outcome = _mapping(case["outcome"], f"case {index}.outcome", ResultValidationError)
        if delivery.get("kind") != "delivery" or use.get("kind") != "observable_use" or outcome.get("kind") != "outcome":
            raise ResultValidationError("delivery, observable-use, and outcome receipts must remain independent")
        if use.get("non_use_inferred") is not False or "used" in use:
            raise ResultValidationError("observable-use receipt must never infer non-use")
        correctness = _mapping(outcome.get("correctness"), f"case {index}.outcome.correctness", ResultValidationError)
        _validate_measure(correctness, f"case {index}.outcome.correctness")
        audit = outcome.get("workspace", {}).get("mutation_audit") if isinstance(outcome.get("workspace"), Mapping) else None
        if not isinstance(audit, Mapping) or not isinstance(audit.get("valid"), bool) or not isinstance(audit.get("off_target"), list):
            raise ResultValidationError("outcome mutation audit is incomplete")
        if case["acceptance"] == "accepted" and audit["valid"] is not True:
            raise ResultValidationError("accepted cases cannot contain an invalidated mutation audit")
        if audit["valid"] is False and (case["acceptance"] != "excluded" or correctness.get("value") != 0.0):
            raise ResultValidationError("off-target mutation must invalidate and zero an excluded case")
        for field in ("calls", "time_ms", "input_tokens", "output_tokens", "cost_usd"):
            _validate_measure(outcome.get("usage", {}).get(field), f"case {index}.outcome.usage.{field}")
        pair_groups.setdefault(str(case["pair_id"]), set()).add(str(case["role"]))
    if any(roles != {"control", "treatment"} for roles in pair_groups.values()):
        raise ResultValidationError("every pair must contain exactly control and treatment")
    if value["accepted_count"] != sum(case["acceptance"] == "accepted" for case in value["cases"]):
        raise ResultValidationError("accepted_count denominator is inconsistent")
    if value["excluded_count"] != sum(case["acceptance"] == "excluded" for case in value["cases"]):
        raise ResultValidationError("excluded_count denominator is inconsistent")

    for index, raw_metric in enumerate(value["metrics"]):
        metric = _mapping(raw_metric, f"result.metrics[{index}]", ResultValidationError)
        for field in ("id", "kind", "unit", "status", "numerator", "denominator", "value"):
            if field not in metric:
                raise ResultValidationError(f"metric {index} missing {field}")
        if not isinstance(metric["id"], str) or not metric["id"]:
            raise ResultValidationError("metric id is invalid")
        if metric["status"] not in {"available", "partial", "unavailable", "not_measured"}:
            raise ResultValidationError("metric capability status is invalid")
        denominator = metric["denominator"]
        if isinstance(denominator, bool) or not isinstance(denominator, int) or denominator <= 0:
            raise ResultValidationError("metric denominator must be complete and positive")
        numerator = metric["numerator"]
        if numerator is not None and (isinstance(numerator, bool) or not isinstance(numerator, (int, float)) or not math.isfinite(float(numerator)) or numerator < 0 or numerator > denominator):
            raise ResultValidationError("metric numerator is invalid or exceeds denominator")
        if metric["status"] in {"available", "partial"}:
            if isinstance(metric["value"], bool) or not isinstance(metric["value"], (int, float)) or not math.isfinite(float(metric["value"])):
                raise ResultValidationError("metric values must be finite")
        elif metric["value"] is not None or not isinstance(metric.get("missing_reason"), str) or not metric["missing_reason"]:
            raise ResultValidationError("unavailable metric needs explicit missingness")

    report = _mapping(value["report"], "result.report", ResultValidationError)
    for field in ("observed", "derived_paired_deltas", "exploratory", "claims_not_established"):
        if field not in report:
            raise ResultValidationError(f"result.report.{field} is required")
    if not isinstance(report["claims_not_established"], list) or not report["claims_not_established"]:
        raise ResultValidationError("claims-not-established section cannot be empty")
    if not isinstance(value["paired_deltas"], list):
        raise ResultValidationError("paired_deltas must be a list")
    expected_digest = sha256_value({key: value[key] for key in value if key != "result_digest"})
    if value["result_digest"] != expected_digest:
        raise ResultValidationError("result_digest does not match result bytes")
    validated = _copy_json(value)
    validated["pair_count"] = len(pair_groups)
    validated["case_ids"] = sorted(seen_cases)
    return validated


def render_report(result: Mapping[str, Any]) -> str:
    """Render only observed/derived/evidence-bound claims; never raw agent output."""
    lines = [
        "# Paired coding-agent utility report", "", "## Observed results",
        f"- Cases completed/retained: {len(result.get('cases', []))}",
        f"- Accepted: {result.get('accepted_count', 0)}; excluded: {result.get('excluded_count', 0)}",
        "- Cohorts are reported separately; unlike task cohorts are not pooled.", "",
        "| cohort | pair | arm | acceptance | correctness | capability |",
        "|---|---|---|---|---:|---|",
    ]
    for case in result.get("cases", []):
        outcome = case.get("outcome", {}).get("correctness", {}).get("value")
        lines.append(f"| {case.get('cohort_id')} | {case.get('pair_id')} | {case.get('role')} | {case.get('acceptance')} | {outcome if outcome is not None else 'missing'} | {case.get('capability', {}).get('status')} |")
    lines.extend(["", "## Derived paired deltas"])
    for item in result.get("paired_deltas", []):
        label = "exploratory" if item.get("exploratory") else "preregistered threshold met"
        lines.append(f"- {item['cohort_id']}: n={item['n_pairs']}, mean treatment-control correctness delta={item['mean_delta']:.6g} ({label}; significance {item['significance']}).")
    if not result.get("paired_deltas"):
        lines.append("- No complete accepted pairs supplied a finite correctness delta.")
    lines.extend(["", "## Exploratory observations"])
    exploratory = result.get("report", {}).get("exploratory", [])
    lines.append("- " + (", ".join(exploratory) if exploratory else "None beyond the preregistered minimum."))
    lines.extend(["", "## Claims not established"])
    for claim in result.get("report", {}).get("claims_not_established", []):
        lines.append(f"- Claim not established: {claim}")
    return "\n".join(lines) + "\n"


_PUBLIC_KEYS = frozenset({
    "schema_version", "protocol_version", "run_id", "challenge_id", "manifest_digest", "comparability_key",
    "result_digest", "accepted_count", "excluded_count", "pair_count", "case_ids", "cases", "metrics",
    "build_under_test", "analysis", "paired_deltas", "report", "observed", "derived_paired_deltas",
    "exploratory", "claims_not_established", "case_id", "pair_id", "cohort_id", "arm_id", "role",
    "status", "acceptance", "exclusion_reasons", "capability", "delivery", "observable_use", "outcome",
    "kind", "delivered", "fixture_id", "fixture_digest", "lower_bound", "non_use_inferred",
    "evidence_status", "marker_observed", "correctness", "workspace", "mutation_audit", "mutation_invalidated", "valid", "off_target",
    "counts", "total", "allowed", "usage", "calls", "time_ms", "input_tokens", "output_tokens",
    "cost_usd", "value", "missing", "missing_reason", "id", "unit", "numerator", "denominator", "reason",
    "n_pairs", "pairs", "control", "treatment", "delta", "mean_delta", "significance", "min_pairs",
    "continuous_metric_min_pairs", "cohort_policy", "paired_metrics", "commit", "digest", "source_commit",
    "verifier_digest", "harness_digest", "image_digest", "reference", "resource_envelope", "count", "metric_id",
})


def sanitize_public_evidence(value: Any, *, _key: str = "") -> Any:
    """Recursively allow-list evidence and drop raw/private values rather than hashing them."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            lowered = key.lower()
            if any(part in lowered for part in _FORBIDDEN_PUBLIC_PARTS) or lowered not in _PUBLIC_KEYS:
                continue
            if lowered.endswith("path") or lowered == "path":
                continue
            safe = sanitize_public_evidence(raw_value, _key=lowered)
            if safe is not None:
                result[key] = safe
        return result
    if isinstance(value, list):
        return [item for item in (sanitize_public_evidence(item, _key=_key) for item in value) if item is not None]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        if value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value):
            return None
        return value if len(value) <= 512 else value[:512]
    return None


def seal_public_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    evidence = sanitize_public_evidence(value)
    sealed = {
        "schema_version": PUBLIC_EVIDENCE_SCHEMA_VERSION,
        "evidence": evidence,
        "evidence_digest": sha256_value(evidence),
    }
    return sealed


def verify_public_evidence(value: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping) or value.get("schema_version") != PUBLIC_EVIDENCE_SCHEMA_VERSION:
        return False
    digest = value.get("evidence_digest")
    evidence = value.get("evidence")
    return isinstance(digest, str) and _HEX64.fullmatch(digest) is not None and digest == sha256_value(evidence)


def run_smoke(manifest_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Materialize both arms and restore treatment fixture without any model call."""
    path = Path(manifest_path).resolve()
    value = load_manifest(path)
    base_dir = path.parent
    runtime = fixture_runtime(value, base_dir)
    preflight = run_preflight(value, runtime=runtime, paid=False)
    if not preflight["ready"]:
        raise PreflightError("offline smoke preflight blocked: " + ", ".join(preflight["failed"]))
    checks = {
        "source_materialized": False, "control_isolated": False, "treatment_fixture_restored": False,
        "verifier_bound": value["verifier"]["input_binding"] == {
            "challenge_id": value["challenge"]["id"], "task_digest": value["challenge"]["task_digest"],
            "source_commit": value["source"]["commit"], "fixture_digest": value["challenge"]["fixture_digest"],
        },
        "mutation_audit_ready": False, "cleanup_verified": False,
    }
    temp_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="perseus-agent-utility-smoke-") as temporary:
        temp_path = Path(temporary)
        arm_projects: dict[str, Path] = {}
        baselines: dict[str, dict[str, Any]] = {}
        source_digest: str | None = None
        for arm in value["arms"]:
            project = temp_path / arm["id"] / "project"
            materialize_gitless_project(base_dir / value["source"]["snapshot_path"], project, value["source"])
            arm_projects[arm["id"]] = project
            source_digest = tree_digest(project)
            if arm["role"] == "treatment":
                receipt = restore_fixture(base_dir, project / ".agent_utility" / "memory-fixture.json", value["fixtures"]["memory"])
                checks["treatment_fixture_restored"] = receipt["observed"] and receipt["fixture_digest"] == value["fixtures"]["memory"]["digest"]
            baselines[arm["id"]] = snapshot_tree(project)
        checks["source_materialized"] = bool(source_digest == value["source"]["tree_digest"] and len(arm_projects) >= 2)
        control = arm_projects[next(arm["id"] for arm in value["arms"] if arm["role"] == "control")]
        treatment = arm_projects[next(arm["id"] for arm in value["arms"] if arm["role"] == "treatment")]
        checks["control_isolated"] = not (control / ".agent_utility" / "memory-fixture.json").exists() and (treatment / ".agent_utility" / "memory-fixture.json").is_file()
        audits = [audit_mutations(project, project, allowed_output_subtrees=value["challenge"]["allowed_output_subtrees"], toolchain_paths=value["challenge"]["toolchain_paths"]) for project in arm_projects.values()]
        checks["mutation_audit_ready"] = all(report["valid"] and report["off_target"] == [] for report in audits) and all(baselines)
    checks["cleanup_verified"] = temp_path is not None and not temp_path.exists()
    if not all(checks.values()):
        raise PreflightError("offline smoke checks failed: " + ", ".join(key for key, ok in checks.items() if not ok))
    return {
        "schema_version": PROTOCOL_VERSION, "status": "passed", "model_calls": 0, "paid_started": False,
        "checks": checks, "spend": {"status": "not_run", "reason": "offline smoke"},
    }


__all__ = [
    "PUBLIC_EVIDENCE_SCHEMA_VERSION", "RESULT_SCHEMA_VERSION", "SCHEMA_VERSION",
    "ManifestError", "MutationAuditError", "PreflightError", "ProtocolError",
    "ResultValidationError", "assert_paid_preflight", "audit_mutations",
    "build_comparability_key", "build_result", "canonical_json", "derive_paired_deltas",
    "fixture_bundle_digest", "fixture_runtime", "load_manifest", "make_delivery_receipt",
    "make_observable_use_receipt", "make_outcome_receipt", "materialize_gitless_project",
    "mutation_audit", "render_report", "restore_fixture", "run_preflight", "run_smoke",
    "sanitize_public_evidence", "seal_manifest", "seal_public_evidence", "sha256_bytes",
    "sha256_value", "snapshot_tree", "tree_digest", "validate_manifest", "validate_result",
    "verify_public_evidence", "workspace_mutation_audit",
]
