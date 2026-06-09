import argparse
import copy
import io
import json
import os
import select
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus, _capture_json, _seed_oracle_log

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

def test_infer_workspace_for_non_dot_perseus_source(tmp_path):
    src = tmp_path / "docs" / "context.md"
    src.parent.mkdir(parents=True)
    src.write_text("@perseus\n")
    assert perseus._infer_workspace(src) == src.parent.resolve()


def test_render_accepts_bare_perseus_header():
    out = perseus.render_source("@perseus\nHello", cfg(), None)
    assert out == "Hello"


def test_render_preserves_directives_inside_fenced_code():
    text = '@perseus\n```markdown\n@date format="YYYY"\n@agora status=open\n```\n@date format="YYYY"'
    out = perseus.render_source(text, cfg(), None)
    assert '```markdown\n@date format="YYYY"\n@agora status=open\n```' in out
    assert out.rstrip().endswith(str(datetime.now().year))


def test_inline_date_preserves_code_span_examples():
    text = '@perseus\n| `@date format="YYYY"` | @date format="YYYY" |'
    out = perseus.render_source(text, cfg(), None)
    assert '`@date format="YYYY"`' in out
    assert f"| {datetime.now().year} |" in out


def test_read_parses_quoted_path_and_fallback_with_quotes(tmp_path):
    workspace = tmp_path
    target = workspace / "a'b.txt"
    target.write_text("content")
    out = perseus.resolve_read(f'"{target.name}" fallback="say \\\"hi\\\""', cfg(), workspace)
    assert "content" in out
    assert out.startswith("```text")


def test_read_blocks_workspace_escape_by_default(tmp_path):
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("nope")
    out = perseus.resolve_read(f'"{outside}"', cfg(), tmp_path)
    assert "escapes workspace" in out


def test_include_blocks_workspace_escape_by_default(tmp_path):
    outside = tmp_path.parent / "secret.md"
    outside.write_text("# secret")
    out = perseus.resolve_include(f'"{outside}"', tmp_path, cfg())
    assert "escapes workspace" in out


def test_if_unknown_condition_emits_warning():
    text = "@perseus\n@if env.eql FOO \"bar\"\nA\n@endif"
    out = perseus.render_source(text, cfg(), None)
    assert "@if error" in out
    assert "unknown @if condition" in out


def test_if_missing_endif_emits_warning():
    text = "@perseus\n@if env.set HOME\nA"
    out = perseus.render_source(text, cfg(), None)
    assert "unmatched @if" in out


def test_services_invalid_entry_reports_warning_row():
    out = perseus.resolve_services("- just-a-string", cfg())
    assert "service entry must be a mapping" in out


def test_services_mapping_format_emits_warning():
    """@services with YAML mapping (dict) instead of list must emit a warning and still process."""
    block = "name: my-app\nurl: http://localhost:9999/health\ntimeout: 3"
    out = perseus.resolve_services(block, cfg())
    assert "YAML mapping detected" in out
    assert "my-app" in out


def test_services_command_disabled_by_default():
    block = "- name: check\n  command: echo hello"
    out = perseus.resolve_services(block, cfg())
    assert "command checks disabled by config" in out


def test_services_blocks_remote_url_by_default():
    """@services must block non-localhost URLs when allow_remote_services_health is False."""
    c = cfg()
    c["render"]["allow_remote_services_health"] = False
    block = "- name: myhost\n  url: http://evil.example.com:8080/health"
    out = perseus.resolve_services(block, c)
    assert "remote blocked" in out or "🔒" in out, f"expected remote URL blocked, got: {out}"


def test_services_allows_localhost_url():
    """@services must allow localhost URLs even when remote check is disabled."""
    c = cfg()
    c["render"]["allow_remote_services_health"] = False
    block = "- name: local\n  url: http://127.0.0.1:9999/health"
    out = perseus.resolve_services(block, c)
    # Should attempt connection (will fail with connection refused, not blocked)
    assert "remote blocked" not in out, f"localhost should not be blocked, got: {out}"


def test_safe_cache_dir_warns_and_audits_when_override_is_rejected(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path / ".perseus")
    c = cfg()
    c["render"]["cache_dir"] = "/etc/perseus-cache"
    c["audit"]["log_path"] = str(tmp_path / ".perseus" / "audit_log.jsonl")

    resolved = perseus._safe_cache_dir(c)
    second = perseus._safe_cache_dir(c)

    assert resolved == tmp_path / ".perseus" / "cache"
    assert second == resolved

    stderr = capsys.readouterr().err
    assert "rejected render.cache_dir outside allowed roots" in stderr
    assert stderr.count("rejected render.cache_dir outside allowed roots") == 1

    audit_log = tmp_path / ".perseus" / "audit_log.jsonl"
    records = [
        json.loads(line)
        for line in audit_log.read_text().splitlines()
        if line.strip()
    ]
    assert any(
        record["event_type"] == "cache_dir_override_rejected"
        and record["configured_path"] == "/etc/perseus-cache"
        and record["fallback_path"] == str(tmp_path / ".perseus" / "cache")
        for record in records
    )


def test_services_respects_allow_remote_enabled():
    """@services must allow remote URLs when allow_remote_services_health is True."""
    c = cfg()
    c["render"]["allow_remote_services_health"] = True
    block = "- name: remote\n  url: http://example.com:80/"
    out = perseus.resolve_services(block, c)
    assert "remote blocked" not in out


def test_services_block_allows_blank_lines_and_explicit_end():
    text = "@perseus\n@services\n- name: one\n  command: echo hi\n\n- name: two\n  command: echo hi\n@end"
    out = perseus.render_source(text, cfg(), None)
    assert "| one |" in out
    assert "| two |" in out


def test_services_empty_explicit_block_warns():
    text = "@perseus\n@services\n@end"
    out = perseus.render_source(text, cfg(), None)
    assert "@services: empty block" in out


def test_query_can_be_disabled_by_config():
    local_cfg = cfg()
    local_cfg["render"]["allow_query_shell"] = False
    out = perseus.resolve_query('"echo hi"', local_cfg)
    assert "@query is disabled by config" in out


def test_query_timeout_modifier_not_leaked_into_unquoted_command():
    # Regression: timeout=N was stripped AFTER command extraction, so an
    # unquoted command swallowed the modifier and ran `echo hello timeout=5`.
    out = perseus.resolve_query("echo hello timeout=5", cfg())
    assert "hello" in out
    assert "timeout=5" not in out


def test_query_timeout_modifier_quoted_command_unaffected():
    out = perseus.resolve_query('"echo hello" timeout=5', cfg())
    assert "hello" in out
    assert "timeout=5" not in out


def test_query_with_schema_validation(tmp_path):
    workspace = tmp_path
    schemas_dir = workspace / ".perseus" / "schemas"
    schemas_dir.mkdir(parents=True)
    schema_file = schemas_dir / "test_schema.yaml"
    schema_file.write_text("""
type: map
mapping:
  "name":
    type: str
    required: true
  "version":
    type: str
    required: true
""")

    # Test with valid data
    valid_yaml = "{name: my-package, version: 1.0.0}"
    out = perseus.resolve_query(f'"echo \'{valid_yaml}\'" schema="test_schema"', cfg(), workspace)
    assert "my-package" in out

    # Test with invalid data
    invalid_yaml = "{name: my-package}"
    out = perseus.resolve_query(f'"echo \'{invalid_yaml}\'" schema="{schema_file}"', cfg(), workspace)
    assert "Validation Error" in out


def test_schema_validator_sequence_pattern_and_enum():
    schema = {
        "type": "seq",
        "items": {
            "type": "map",
            "mapping": {
                "name": {"type": "str", "required": True, "pattern": "^[a-z]+$"},
                "kind": {"type": "str", "required": True, "enum": ["app", "lib"]},
            },
        },
    }

    assert perseus._validate_basic_schema([{"name": "api", "kind": "app"}], schema) == []
    errors = perseus._validate_basic_schema([{"name": "API", "kind": "tool"}], schema)
    assert any("does not match" in e for e in errors)
    assert any("expected one of" in e for e in errors)


def test_read_schema_validates_full_structured_file(tmp_path):
    schemas_dir = tmp_path / ".perseus" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "service.yaml").write_text("""
type: map
mapping:
  service:
    type: map
    required: true
    mapping:
      port:
        type: int
        required: true
""")
    (tmp_path / "service.yaml").write_text("service:\n  port: 3000\n")

    out = perseus.resolve_read('service.yaml schema="service"', cfg(), tmp_path)
    assert "port: 3000" in out


def test_read_schema_validates_extracted_path(tmp_path):
    schemas_dir = tmp_path / ".perseus" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "port.yaml").write_text("type: int\n")
    (schemas_dir / "string.yaml").write_text("type: str\n")
    (tmp_path / "service.yaml").write_text("service:\n  port: 3000\n")

    out = perseus.resolve_read('service.yaml path="service.port" schema="port"', cfg(), tmp_path)
    assert out == "3000"

    out = perseus.resolve_read('service.yaml path="service.port" schema="string"', cfg(), tmp_path)
    assert "Validation Error" in out


def test_read_schema_validates_env_key_and_fallback(tmp_path):
    schemas_dir = tmp_path / ".perseus" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "mode.yaml").write_text('type: str\npattern: "^(dev|prod)$"\n')
    (tmp_path / ".env").write_text("MODE=prod\n")

    out = perseus.resolve_read('.env key="MODE" schema="mode"', cfg(), tmp_path)
    assert out == "prod"

    out = perseus.resolve_read('.env key="MISSING" fallback="stage" schema="mode"', cfg(), tmp_path)
    assert "Validation Error" in out


def test_env_schema_validates_value_and_fallback(monkeypatch, tmp_path):
    schemas_dir = tmp_path / ".perseus" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "env.yaml").write_text('type: str\npattern: "^(dev|prod)$"\n')
    monkeypatch.setenv("DEPLOY_ENV", "prod")

    out = perseus.resolve_env('DEPLOY_ENV schema="env"', cfg(), tmp_path)
    assert out == "prod"

    monkeypatch.delenv("DEPLOY_ENV")
    out = perseus.resolve_env('DEPLOY_ENV fallback="stage" schema="env"', cfg(), tmp_path)
    assert "Validation Error" in out


def test_validate_block_validates_rendered_payload(tmp_path):
    schemas_dir = tmp_path / ".perseus" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "service.yaml").write_text("""
type: map
mapping:
  service:
    type: map
    required: true
    mapping:
      port:
        type: int
        required: true
""")
    (tmp_path / "service.yaml").write_text("service:\n  port: 3000\n")

    src = '@perseus\n@validate schema="service"\n@read service.yaml\n@end'
    out = perseus.render_source(src, cfg(), tmp_path)
    assert "port: 3000" in out
    assert "Validation Error" not in out

    (tmp_path / "service.yaml").write_text("service:\n  port: no\n")
    out = perseus.render_source(src, cfg(), tmp_path)
    assert "Validation Error" in out


def test_registry_output_schema_validates_annotated_directive(monkeypatch):
    spec = perseus.DIRECTIVE_REGISTRY["@date"]
    assert spec.output_schema is not None

    monkeypatch.setitem(
        perseus.DIRECTIVE_REGISTRY,
        "@date",
        spec._replace(resolver=lambda args: ""),
    )

    out = perseus.render_source('@perseus\n@date format="YYYY"', cfg(), None)
    assert "Validation Error" in out
    assert "`@date`" in out


def test_explicit_schema_takes_precedence_over_registry_output_schema(monkeypatch, tmp_path):
    schemas_dir = tmp_path / ".perseus" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "number.yaml").write_text("type: int\n")
    (tmp_path / "service.yaml").write_text("service:\n  port: 3000\n")

    spec = perseus.DIRECTIVE_REGISTRY["@read"]
    monkeypatch.setitem(
        perseus.DIRECTIVE_REGISTRY,
        "@read",
        spec._replace(output_schema={"type": "str", "pattern": "^NEVER$"}),
    )

    out = perseus.render_source(
        '@perseus\n@read service.yaml path="service.port" schema="number"',
        cfg(),
        tmp_path,
    )
    assert out == "3000"


def test_directive_graph_skips_fenced_code_and_uses_registry_metadata(tmp_path):
    source = """@perseus
```markdown
@query "exit 99"
```
@read config.yaml path="service.port"
@env DEPLOY_ENV
"""
    graph = perseus.directive_dependency_graph(source, source_name="ctx.md", workspace=tmp_path)

    directives = [node["directive"] for node in graph["nodes"]]
    assert directives == ["@read", "@env"]
    assert graph["nodes"][0]["metadata"]["reads_files"] is True
    assert graph["nodes"][1]["metadata"]["cacheable"] is False


def test_directive_graph_reports_static_resource_hints(tmp_path):
    source = """@perseus
@read config.yaml path="service.port" schema="port"
@include docs/setup.md
@list packages type="dirs"
@tree src depth=2
@env DEPLOY_ENV schema="env"
"""
    graph = perseus.directive_dependency_graph(source, workspace=tmp_path)

    resources = {
        node["directive"]: {(item["kind"], item["value"]) for item in node["resources"]}
        for node in graph["nodes"]
    }
    assert ("file", "config.yaml") in resources["@read"]
    assert ("path", "service.port") in resources["@read"]
    assert ("schema", "port") in resources["@read"]
    assert ("file", "docs/setup.md") in resources["@include"]
    assert ("directory", "packages") in resources["@list"]
    assert ("directory", "src") in resources["@tree"]
    assert ("env", "DEPLOY_ENV") in resources["@env"]
    assert ("schema", "env") in resources["@env"]


def test_directive_graph_does_not_execute_shell_directives(tmp_path):
    graph = perseus.directive_dependency_graph('@perseus\n@query "exit 99"', workspace=tmp_path)

    assert graph["summary"]["node_count"] == 1
    assert graph["nodes"][0]["directive"] == "@query"
    assert graph["nodes"][0]["metadata"]["executes_shell"] is True
    assert graph["nodes"][0]["resources"] == [{"kind": "shell", "value": "exit 99"}]


def test_prefetch_rules_match_graph_and_write_cache(tmp_path):
    local = cfg()
    local["render"]["cache_dir"] = str(tmp_path / "cache")
    local["prefetch"]["rules"] = [{
        "name": "read-md",
        "trigger": {"directive": "@read", "resource": "*.md"},
        "prefetch": ['@query "printf prefetched" @cache ttl=120'],
    }]

    result = perseus.prefetch_source("@perseus\n@read README.md\n", local, tmp_path, "ctx.md")

    assert result["summary"]["matches"] == 1
    assert result["summary"]["ran"] == 1
    cache_key = perseus._cache_key('@query "printf prefetched"')
    cached = perseus.cache_get(cache_key, "ttl", 120, local)
    assert cached is not None
    assert "prefetched" in cached


def test_prefetch_respects_disabled_query_gate(tmp_path):
    local = cfg()
    local["render"]["cache_dir"] = str(tmp_path / "cache")
    local["render"]["allow_query_shell"] = False
    local["prefetch"]["rules"] = [{
        "trigger": "@read",
        "prefetch": ['@query "printf blocked" @cache ttl=120'],
    }]

    result = perseus.prefetch_source("@perseus\n@read README.md\n", local, tmp_path, "ctx.md")

    assert result["summary"]["ran"] == 0
    assert result["summary"]["skipped"] == 1
    assert result["results"][0]["reason"] == "render.allow_query_shell=false"
    cache_key = perseus._cache_key('@query "printf blocked"')
    assert perseus.cache_get(cache_key, "ttl", 120, local) is None


def test_prefetch_reports_no_match_behavior(tmp_path):
    local = cfg()
    local["prefetch"]["rules"] = [{
        "trigger": "@env",
        "prefetch": ['@query "printf unused" @cache ttl=120'],
    }]

    result = perseus.prefetch_source("@perseus\n@read README.md\n", local, tmp_path, "ctx.md")
    human = perseus.format_prefetch_human(result)

    assert result["summary"]["matches"] == 0
    assert result["results"] == []
    assert "No prefetch rules matched." in human


def test_prefetch_trigger_string_can_include_args(tmp_path):
    (tmp_path / "README.md").write_text("prefetched read")
    local = cfg()
    local["render"]["cache_dir"] = str(tmp_path / "cache")
    local["prefetch"]["rules"] = [{
        "trigger": '@query "git status"',
        "prefetch": ['@read README.md @cache ttl=120'],
    }]

    result = perseus.prefetch_source('@perseus\n@query "git status"\n', local, tmp_path, "ctx.md")

    assert result["summary"]["matches"] == 1
    assert result["summary"]["ran"] == 1
    cache_key = perseus._cache_key("@read README.md")
    assert "prefetched read" in perseus.cache_get(cache_key, "ttl", 120, local)


def test_prefetch_skips_directives_without_cache_modifier(tmp_path):
    local = cfg()
    local["prefetch"]["rules"] = [{
        "trigger": "@read",
        "prefetch": ['@query "printf uncached"'],
    }]

    result = perseus.prefetch_source("@perseus\n@read README.md\n", local, tmp_path, "ctx.md")

    assert result["summary"]["ran"] == 0
    assert result["summary"]["skipped"] == 1
    assert "require @cache" in result["results"][0]["reason"]


def test_adaptive_prefetch_disabled_does_not_score_or_execute(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: called.append(a) or ("[]", 0))
    local = cfg()
    local["render"]["cache_dir"] = str(tmp_path / "cache")
    local["prefetch"]["adaptive"] = {
        "enabled": False,
        "backend": "daedalus",
        "candidates": [{
            "id": "off",
            "prefetch": '@query "printf off" @cache ttl=120',
            "patterns": ["off"],
        }],
    }

    result = perseus.prefetch_source("@perseus\n@read README.md\n", local, tmp_path, "ctx.md")

    assert result["adaptive"]["enabled"] is False
    assert result["results"] == []
    assert called == []
    cache_key = perseus._cache_key('@query "printf off"')
    assert perseus.cache_get(cache_key, "ttl", 120, local) is None


def test_adaptive_prefetch_deterministic_scores_patterns(monkeypatch, tmp_path):
    _seed_oracle_log(monkeypatch, tmp_path, [{
        "accepted": True,
        "prompt": "Need decision context",
        "response": "Use memory for decisions before task planning",
    }])
    local = cfg()
    local["render"]["cache_dir"] = str(tmp_path / "cache")
    local["prefetch"]["adaptive"] = {
        "enabled": True,
        "backend": "deterministic",
        "threshold": 0.5,
        "candidates": [{
            "id": "decision-memory",
            "trigger": "@read README.md",
            "prefetch": '@query "printf adaptive" @cache ttl=120',
            "patterns": ["decision", "memory"],
        }],
    }

    result = perseus.prefetch_source("@perseus\n@read README.md\n", local, tmp_path, "ctx.md")

    assert result["adaptive"]["backend"] == "deterministic"
    assert result["adaptive"]["selected"] == 1
    assert result["summary"]["ran"] == 1
    assert result["results"][0]["rule"] == "adaptive:decision-memory"
    assert "matched patterns" in result["results"][0]["reason"]
    cache_key = perseus._cache_key('@query "printf adaptive"')
    assert "adaptive" in perseus.cache_get(cache_key, "ttl", 120, local)


def test_adaptive_prefetch_daedalus_unavailable_falls_back(monkeypatch, tmp_path):
    _seed_oracle_log(monkeypatch, tmp_path, [{
        "accepted": True,
        "prompt": "Need decision context",
        "response": "Use memory for decisions before task planning",
    }])
    seen = {}

    def fake_run_llm(provider, prompt, cfg_, model=None, model_url=None):
        seen["provider"] = provider
        seen["prompt"] = prompt
        return ("> ⚠ unavailable", 2)

    monkeypatch.setattr(perseus, "run_llm", fake_run_llm)
    local = cfg()
    local["render"]["cache_dir"] = str(tmp_path / "cache")
    local["prefetch"]["adaptive"] = {
        "enabled": True,
        "backend": "daedalus",
        "threshold": 0.5,
        "candidates": [{
            "id": "decision-memory",
            "prefetch": '@query "printf fallback" @cache ttl=120',
            "patterns": ["decision", "memory"],
        }],
    }

    result = perseus.prefetch_source("@perseus\n@read README.md\n", local, tmp_path, "ctx.md")

    assert seen["provider"] == "daedalus"
    assert "Do not invent directives" in seen["prompt"]
    assert result["adaptive"]["backend"] == "deterministic"
    assert "daedalus failed" in result["adaptive"]["fallback_reason"]
    assert result["summary"]["ran"] == 1
    assert "deterministic fallback" in result["results"][0]["reason"]


def test_adaptive_prefetch_skips_below_threshold_without_execution(tmp_path):
    local = cfg()
    local["render"]["cache_dir"] = str(tmp_path / "cache")
    local["prefetch"]["adaptive"] = {
        "enabled": True,
        "threshold": 0.9,
        "candidates": [{
            "id": "too-cold",
            "prefetch": '@query "printf should-not-run" @cache ttl=120',
            "patterns": ["absent-pattern"],
        }],
    }

    result = perseus.prefetch_source("@perseus\n@read README.md\n", local, tmp_path, "ctx.md")

    assert result["summary"]["ran"] == 0
    assert result["summary"]["skipped"] == 1
    assert "adaptive score 0.00 < threshold 0.90" in result["results"][0]["reason"]
    cache_key = perseus._cache_key('@query "printf should-not-run"')
    assert perseus.cache_get(cache_key, "ttl", 120, local) is None



def test_skills_frontmatter_parses_structurally(tmp_path):
    skill_dir = tmp_path / "skills" / "cat" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo-name\ndescription: uses --- inside text ok\n---\nbody")
    local_cfg = cfg()
    local_cfg["pythia"]["skill_dir"] = str(tmp_path / "skills")
    out = perseus.resolve_skills("", local_cfg)
    assert "demo-name" in out
    assert "uses --- inside text ok" in out
# ── task-08: @list and @tree ─────────────────────────────────────────────────

def test_list_directory_simple(tmp_path):
    local = cfg()
    (tmp_path / "packages" / "api").mkdir(parents=True)
    (tmp_path / "packages" / "web").mkdir(parents=True)
    out = perseus.resolve_list('./packages/ type="dirs" depth=1 as="list"', local, tmp_path)
    assert "- api/" in out
    assert "- web/" in out


def test_list_structured_json_table(tmp_path):
    local = cfg()
    pkg = tmp_path / "package.json"
    pkg.write_text(json.dumps({"scripts": {"dev": "vite dev", "build": "vite build"}}))
    out = perseus.resolve_list('./package.json path="scripts" columns="key:Command,value:Runs" as="table"', local, tmp_path)
    assert "| Command | Runs |" in out
    assert "dev" in out
    assert "vite build" in out


def test_list_missing_path_warns(tmp_path):
    out = perseus.resolve_list('./nope', cfg(), tmp_path)
    assert "not found" in out


def test_list_outside_workspace_warns(tmp_path):
    local = cfg()
    local["render"]["allow_outside_workspace"] = False
    other = tmp_path.parent / "other-ws"
    other.mkdir(exist_ok=True)
    out = perseus.resolve_list(str(other), local, tmp_path)
    assert "escapes workspace" in out


def test_tree_basic(tmp_path):
    local = cfg()
    (tmp_path / "src" / "api").mkdir(parents=True)
    (tmp_path / "src" / "api" / "routes.py").write_text("")
    (tmp_path / "src" / "api" / "models.py").write_text("")
    (tmp_path / "src" / "utils").mkdir(parents=True)
    (tmp_path / "src" / "utils" / "parser.py").write_text("")
    out = perseus.resolve_tree('./src/ depth=3', local, tmp_path)
    assert "```" in out
    assert "src/" in out
    assert "routes.py" in out
    assert "parser.py" in out


def test_tree_match_and_exclude(tmp_path):
    local = cfg()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("")
    (tmp_path / "src" / "b.txt").write_text("")
    (tmp_path / "src" / "node_modules").mkdir()
    (tmp_path / "src" / "node_modules" / "x.py").write_text("")
    out = perseus.resolve_tree('./src/ depth=2 match="*.py" exclude="node_modules"', local, tmp_path)
    assert "a.py" in out
    assert "b.txt" not in out
    assert "node_modules" not in out


def test_list_and_tree_dispatch_through_render(tmp_path):
    local = cfg()
    (tmp_path / "pkgs").mkdir()
    (tmp_path / "pkgs" / "x").mkdir()
    src = ['@list ./pkgs type="dirs"']
    out = perseus._render_lines(src, local, workspace=tmp_path)
    assert "- x/" in out
# ─────────────────────────────────────────────────────────────────────────────
# task-14: @query fallback="text"
# ─────────────────────────────────────────────────────────────────────────────

def test_query_fallback_on_failed_command():
    out = perseus.resolve_query('"false" fallback="no git here"', cfg())
    assert out == "no git here"


def test_query_fallback_on_empty_stdout():
    out = perseus.resolve_query('"true" fallback="no output"', cfg())
    assert out == "no output"


def test_query_fallback_ignored_on_success():
    out = perseus.resolve_query('"echo hello" fallback="never seen"', cfg())
    assert "hello" in out
    assert "never seen" not in out


def test_query_no_fallback_still_shows_warning_on_failure():
    out = perseus.resolve_query('"false"', cfg())
    assert "⚠" in out or "exited" in out


def test_query_fallback_single_quoted():
    out = perseus.resolve_query("\"false\" fallback='single-q text'", cfg())
    assert out == "single-q text"


def test_query_fallback_with_cache_modifier_stripped_first(monkeypatch):
    # When @cache is stripped before fallback parsing, fallback should still work.
    raw = '"false" fallback="cached fallback" @cache ttl=10'
    # The renderer normally strips @cache; we strip manually here to simulate
    cleaned, _, _, _ = perseus._parse_cache_modifier(raw)
    out = perseus.resolve_query(cleaned, cfg())
    assert out == "cached fallback"


# ─────────────────────────────────────────────────────────────────────────────
# Dependency-fingerprinted cache invalidation
# ─────────────────────────────────────────────────────────────────────────────

def test_cache_fingerprint_read_invalidates_on_file_change(tmp_path):
    """Changing a @read file within TTL invalidates the cache."""
    src = tmp_path / "src.md"
    data_file = tmp_path / "data.txt"
    data_file.write_text("v1")
    src.write_text(f'@perseus v0.4\n@read {data_file} @cache ttl=3600')

    c = cfg()
    c["render"]["cache_dir"] = str(tmp_path / "cache")

    r1 = perseus.render_source(src.read_text(), c, tmp_path)
    assert "v1" in r1

    # Change the file — cache must invalidate
    data_file.write_text("v2")
    r2 = perseus.render_source(src.read_text(), c, tmp_path)
    assert "v2" in r2


def test_cache_fingerprint_handles_quoted_paths_with_spaces(tmp_path):
    """Quoted file paths with spaces still participate in dependency invalidation."""
    src = tmp_path / "src.md"
    data_file = tmp_path / "data file.txt"
    data_file.write_text("v1")
    src.write_text('@perseus v0.4\n@read "data file.txt" @cache ttl=3600')

    c = cfg()
    c["render"]["cache_dir"] = str(tmp_path / "cache")

    r1 = perseus.render_source(src.read_text(), c, tmp_path)
    assert "v1" in r1

    data_file.write_text("v2")
    r2 = perseus.render_source(src.read_text(), c, tmp_path)
    assert "v2" in r2


def test_cache_fingerprint_respects_workspace_boundary(monkeypatch, tmp_path):
    """Fingerprinting must not read paths that the resolver would block."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")

    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(self):
        if self.resolve(strict=False) == outside.resolve():
            raise AssertionError("fingerprint read escaped workspace")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    c = cfg()
    c["render"]["cache_dir"] = str(tmp_path / "cache")
    out = perseus.render_source(
        f"@perseus v0.4\n@read {outside} @cache ttl=3600",
        c,
        workspace,
    )

    assert "path escapes workspace" in out


def test_cache_fingerprint_no_deps_still_caches(tmp_path):
    """@query with no file deps caches and returns consistent output."""
    src = tmp_path / "src.md"
    src.write_text('@perseus v0.4\n@query "echo hello" @cache ttl=3600')

    c = cfg()
    c["render"]["cache_dir"] = str(tmp_path / "cache")

    r1 = perseus.render_source(src.read_text(), c, tmp_path)
    r2 = perseus.render_source(src.read_text(), c, tmp_path)
    assert r1 == r2  # cached output matches


def test_cache_fingerprint_memory_changes_with_mneme_config(tmp_path):
    """Changing the active Mneme connector config invalidates @memory cache keys."""
    c1 = cfg()
    c1["mneme"]["command"] = ["mneme"]
    c2 = cfg()
    c2["mneme"]["command"] = ["mneme", "--db", "/tmp/other-mneme.db"]

    fp1 = perseus._dependency_fingerprint(
        "@memory",
        'mode=search query="architecture"',
        tmp_path,
        c1,
    )
    fp2 = perseus._dependency_fingerprint(
        "@memory",
        'mode=search query="architecture"',
        tmp_path,
        c2,
    )

    assert fp1
    assert fp2
    assert fp1 != fp2


def test_cache_nofingerprint_ignores_file_change(tmp_path):
    """@cache nofingerprint keeps TTL-only behavior, ignores file changes."""
    src = tmp_path / "src.md"
    data_file = tmp_path / "data.txt"
    data_file.write_text("v1")
    src.write_text(f'@perseus v0.4\n@read {data_file} @cache nofingerprint ttl=3600')

    c = cfg()
    c["render"]["cache_dir"] = str(tmp_path / "cache")

    r1 = perseus.render_source(src.read_text(), c, tmp_path)
    assert "v1" in r1

    data_file.write_text("v2")
    r2 = perseus.render_source(src.read_text(), c, tmp_path)
    # With nofingerprint, cache is NOT invalidated by file change
    assert "v1" in r2


def test_query_fallback_unescapes_simple_escapes():
    out = perseus.resolve_query(r'"false" fallback="line one\nline two"', cfg())
    assert "line one\nline two" == out


# ─────────────────────────────────────────────────────────────────────────────
# task-13: @if query("...") matches /regex/
# ─────────────────────────────────────────────────────────────────────────────

def test_if_query_matches_true():
    assert perseus.evaluate_condition(
        'query("echo hello world") matches /hello/',
        workspace=None,
        cfg=cfg(),
    ) is True


def test_if_query_matches_false():
    assert perseus.evaluate_condition(
        'query("echo goodbye") matches /hello/',
        workspace=None,
        cfg=cfg(),
    ) is False


def test_if_query_not_matches_true():
    assert perseus.evaluate_condition(
        'query("echo goodbye") not matches /hello/',
        workspace=None,
        cfg=cfg(),
    ) is True


def test_if_query_not_matches_false():
    assert perseus.evaluate_condition(
        'query("echo hello world") not matches /hello/',
        workspace=None,
        cfg=cfg(),
    ) is False


def test_if_query_respects_allow_query_shell_false(capsys):
    local = cfg()
    local["render"]["allow_query_shell"] = False
    result = perseus.evaluate_condition(
        'query("echo hello") matches /hello/',
        workspace=None,
        cfg=local,
    )
    assert result is False
    err = capsys.readouterr().err
    assert "allow_query_shell" in err


def test_if_query_case_insensitive_flag():
    assert perseus.evaluate_condition(
        'query("echo HELLO") matches /hello/i',
        workspace=None,
        cfg=cfg(),
    ) is True


def test_if_query_invalid_regex_raises():
    with pytest.raises(perseus.ConditionParseError):
        perseus.evaluate_condition(
            'query("echo x") matches /[unclosed/',
            workspace=None,
            cfg=cfg(),
        )


def test_if_query_failed_command_returns_false(capsys):
    # `false` always exits non-zero with empty stdout — the regex can't match empty
    assert perseus.evaluate_condition(
        'query("false") matches /anything/',
        workspace=None,
        cfg=cfg(),
    ) is False


def test_if_query_matches_inside_render_block():
    cfg_local = cfg()
    cfg_local["render"]["allow_query_shell"] = True
    src = """@perseus v0.6

@if query("echo present") matches /present/
SHOWN
@else
HIDDEN
@endif
"""
    rendered = perseus.render_source(src, cfg_local, workspace=None)
    assert "SHOWN" in rendered
    assert "HIDDEN" not in rendered
# ═══════════════════════════════════════════════════════════════════════════════
# Task-25: DIRECTIVE_REGISTRY invariant tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_registry_every_directive_has_callable_resolver_or_is_control():
    """Every registered directive with kind='inline' must have a callable resolver."""
    for name, spec in perseus.DIRECTIVE_REGISTRY.items():
        if spec.kind == "inline":
            assert callable(spec.resolver), f"{name}: inline directive must have callable resolver"
        # Control/block directives may have None resolver
        if spec.kind == "control":
            assert spec.resolver is None, f"{name}: control directive should have no resolver"


def test_registry_unsafe_hover_invariant():
    """Directives that execute shell or mutate state must NOT be safe_for_hover."""
    for name, spec in perseus.DIRECTIVE_REGISTRY.items():
        if spec.executes_shell or spec.mutates_state:
            assert not spec.safe_for_hover, (
                f"{name}: executes_shell={spec.executes_shell} mutates_state={spec.mutates_state} "
                f"but safe_for_hover=True — violates safety invariant"
            )


def test_registry_inline_re_matches_all_inline_directives():
    """INLINE_DIRECTIVE_RE must match every registered inline directive."""
    for name, spec in perseus.DIRECTIVE_REGISTRY.items():
        if spec.kind == "inline":
            m = perseus.INLINE_DIRECTIVE_RE.match(name)
            assert m is not None, f"{name}: not matched by INLINE_DIRECTIVE_RE"
            m2 = perseus.INLINE_DIRECTIVE_RE.match(f"{name} some_arg=value")
            assert m2 is not None, f"{name} with args: not matched by INLINE_DIRECTIVE_RE"


def test_registry_no_unknown_call_sigs():
    """call_sig must be one of the known adapter patterns."""
    valid = {"acw", "ac", "a", "awc", "block"}
    for name, spec in perseus.DIRECTIVE_REGISTRY.items():
        assert spec.call_sig in valid, f"{name}: unknown call_sig={spec.call_sig!r}"


def test_registry_completeness_against_resolver_functions():
    """Every resolve_* function in perseus module should be in the registry."""
    import inspect
    resolver_funcs = {
        name for name, obj in inspect.getmembers(perseus, inspect.isfunction)
        if name.startswith("resolve_")
    }
    registered_resolvers = {
        spec.resolver.__name__ for spec in perseus.DIRECTIVE_REGISTRY.values()
        if spec.resolver is not None
    }
    missing = resolver_funcs - registered_resolvers
    assert not missing, f"resolve_* functions not in registry: {missing}"


def test_date_format_rejects_backslash_as_quote_delimiter():
    """@date format=\\YYYY\\ should fall through to default — backslash is not a valid quote."""
    result = perseus.resolve_date('format=\\YYYY\\')
    # Default format: "2026-05-22 21:20 CDT" — contains digits, dashes, colon, timezone
    # It should NOT return just the year "2026" (which would mean backslash was matched)
    assert len(result) > 10, f"expected default format, got {result!r}"


def test_date_format_backreference_correctly_pairs_quotes():
    """Backreference must not let single quote close a double-quoted value."""
    # format="YYYY' — mismatched quotes should fall through
    result = perseus.resolve_date("format=\"YYYY'")
    assert len(result) > 10, f"unpaired quotes should fall through: got {result!r}"


# ── Regression: #37 / #38 — max_bytes NameError on malformed config ──────────

def test_include_survives_malformed_max_include_bytes(tmp_path):
    """#37: resolve_include must not raise NameError when max_include_bytes is a non-integer."""
    c = cfg()
    c["render"]["max_include_bytes"] = "not-an-int"
    f = tmp_path / "hello.md"
    f.write_text("# hello\n")
    result = perseus.resolve_include(f'"{f.name}"', tmp_path, c)
    assert "# hello" in result


def test_read_survives_malformed_max_read_bytes(tmp_path):
    """#38: resolve_read must not raise NameError when max_read_bytes is a non-integer."""
    c = cfg()
    c["render"]["max_read_bytes"] = "not-an-int"
    f = tmp_path / "hello.txt"
    f.write_text("hello")
    result = perseus.resolve_read(f'"{f.name}"', c, tmp_path)
    assert "hello" in result
