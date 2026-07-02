"""#607 — @speculate: speculative context prefetch via next-intent prediction.

Covers the acceptance criteria from the issue:
  * On a replayed A→B→A→B session, the Markov predictor's top-1 accuracy
    beats the naive most-recent baseline (deterministic, fixed corpus).
  * Speculative warms are bounded by the token budget.
  * Disabled (`speculate.enabled: false`, the default) == zero cache writes,
    zero stats writes, zero behavior change.
  * Key parity: a speculative warm is read by the real render path (same
    base+fingerprint, workspace-scoped key derivation as real prefetch).
  * Confidence gating, hit/miss settlement, and stats round-trip.
"""

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import yaml

from conftest import perseus, cfg, _capture_json


ROOT = Path(__file__).resolve().parents[1]


# ── helpers ───────────────────────────────────────────────────────────────────

def _mkcfg(tmp_path):
    c = cfg()
    c["checkpoints"]["store"] = str(tmp_path / "checkpoints")
    c["render"]["cache_dir"] = str(tmp_path / "cache")
    return c


def _seed_checkpoints(store: Path, tasks, start=0):
    """Write one checkpoint YAML per task, in chronological filename order."""
    store.mkdir(parents=True, exist_ok=True)
    for i, task in enumerate(tasks, start=start):
        cp = {"version": 1, "written": f"2026-01-01T{i:02d}:00:00", "task": task}
        (store / f"2026-01-01T{i:04d}.yaml").write_text(
            yaml.dump(cp, default_flow_style=False), encoding="utf-8"
        )


def _cache_dir_files(c):
    d = Path(c["render"]["cache_dir"])
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


# ── predictor: A→B→A→B replay beats most-recent baseline ─────────────────────

def test_markov_top1_beats_most_recent_baseline_on_abab_replay():
    seq = ["A", "B"] * 4  # A B A B A B A B
    markov_correct = baseline_correct = evaluated = 0
    for i in range(2, len(seq)):
        prefix, actual = seq[:i], seq[i]
        predictor = perseus.MarkovIntentPredictor()
        predictor.fit(prefix)
        top = predictor.predict(prefix[-1], 1)
        if top and top[0][0] == actual:
            markov_correct += 1
        if perseus.most_recent_baseline(prefix) == actual:
            baseline_correct += 1
        evaluated += 1
    assert evaluated > 0
    # Strict alternation: Markov is exact, most-recent is always wrong.
    assert markov_correct == evaluated
    assert baseline_correct == 0
    assert markov_correct / evaluated > baseline_correct / evaluated


def test_markov_probabilities_frequency_fallback_and_deterministic_tiebreak():
    predictor = perseus.MarkovIntentPredictor()
    predictor.fit(["A", "B", "A", "C", "A"])
    # Known current intent → transition table: A→B once, A→C once (tie → alpha).
    top = predictor.predict("A", 2)
    assert top == [("B", 0.5), ("C", 0.5)]
    # Unseen current intent → global frequency fallback, A dominates.
    fallback = predictor.predict("ZZZ", 3)
    assert fallback[0] == ("A", 0.6)
    assert [name for name, _p in fallback] == ["A", "B", "C"]
    # Empty history → no predictions.
    empty = perseus.MarkovIntentPredictor()
    empty.fit([])
    assert empty.predict(None, 3) == []


# ── @speculate pragma parsing ─────────────────────────────────────────────────

def test_speculate_pragma_parsed_and_stripped_fence_aware():
    lines = [
        "hello",
        "@speculate k=2 budget=150",
        "```",
        "@speculate k=9 budget=9",   # inside a fence: content, not a pragma
        "```",
        "world",
    ]
    out, params = perseus._extract_speculate_pragmas(lines)
    assert params == {"k": 2, "budget": 150}
    assert "@speculate k=2 budget=150" not in out
    assert "@speculate k=9 budget=9" in out  # fenced copy preserved
    assert out[0] == "hello" and out[-1] == "world"

    # No pragma present → params is None, lines untouched.
    out2, params2 = perseus._extract_speculate_pragmas(["a", "b"])
    assert params2 is None and out2 == ["a", "b"]


def test_render_strips_speculate_pragma_from_output(tmp_path):
    c = _mkcfg(tmp_path)
    src = "@perseus v1\n\nHello there.\n@speculate k=2 budget=50\nGoodbye.\n"
    out = perseus.render_source(src, c, None)
    assert "@speculate" not in out
    assert "Hello there." in out and "Goodbye." in out


# ── disabled == zero interference ─────────────────────────────────────────────

def test_disabled_speculation_makes_zero_cache_and_stats_writes(tmp_path):
    c = _mkcfg(tmp_path)  # speculate.enabled defaults to False
    _seed_checkpoints(Path(c["checkpoints"]["store"]), ["A", "B", "A", "B"])
    c["speculate"] = dict(perseus.DEFAULT_CONFIG["speculate"])
    c["speculate"]["intents"] = {"A": ['@read "notes.md" @cache ttl=300']}

    result = perseus.run_speculation(c, None)
    assert result["enabled"] is False
    assert result["predicted"] == [] and result["results"] == []
    assert _cache_dir_files(c) == []
    assert not perseus._speculate_stats_path(c, None).exists()

    # Rendering a source that carries the pragma is also a no-op when disabled.
    out = perseus.render_source(
        "@perseus v1\n\nPlain text only.\n@speculate k=3 budget=100\n", c, None
    )
    assert "@speculate" not in out
    assert _cache_dir_files(c) == []
    assert not perseus._speculate_stats_path(c, None).exists()


def test_prefetch_source_omits_speculate_key_when_disabled(tmp_path):
    c = _mkcfg(tmp_path)
    result = perseus.prefetch_source("@perseus v1\n\nhello\n", c)
    assert "speculate" not in result

    c["speculate"] = dict(perseus.DEFAULT_CONFIG["speculate"])
    c["speculate"]["enabled"] = True
    result2 = perseus.prefetch_source("@perseus v1\n\nhello\n", c)
    assert "speculate" in result2
    assert result2["speculate"]["enabled"] is True
    assert "predicted" in result2["speculate"]


# ── warming: key parity with the real render path ─────────────────────────────

def test_speculative_warm_is_read_by_real_render(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "notes.md").write_text("alpha speculation notes", encoding="utf-8")

    c = _mkcfg(tmp_path)
    c["speculate"] = dict(perseus.DEFAULT_CONFIG["speculate"])
    c["speculate"].update({
        "enabled": True,
        "intents": {"A": ['@read "notes.md" @cache ttl=300']},
    })
    _seed_checkpoints(Path(c["checkpoints"]["store"]), ["A", "B", "A", "B"])

    result = perseus.run_speculation(c, ws)
    assert result["enabled"] is True
    assert result["current_intent"] == "B"
    assert result["predicted"][0]["intent"] == "A"
    assert result["predicted"][0]["probability"] == 1.0
    assert result["summary"]["warmed"] == 1

    # The probe helper agrees the entry is warm (same key derivation).
    probe = perseus._speculate_probe(
        '@read "notes.md" @cache ttl=300', c, ws)
    assert probe["warm"] is True

    # The REAL render path reads the speculative entry: a pure cache hit.
    stats = {"directive_count": 0, "cache_hits": 0, "cache_misses": 0}
    out = perseus.render_source(
        '@perseus v1\n\n@read "notes.md" @cache ttl=300\n', c, ws, _stats=stats)
    assert "alpha speculation notes" in out
    assert stats["cache_hits"] == 1
    assert stats["cache_misses"] == 0


def test_render_with_pragma_triggers_speculation_only_when_enabled(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runbook.md").write_text("deploy runbook", encoding="utf-8")

    c = _mkcfg(tmp_path)
    c["speculate"] = dict(perseus.DEFAULT_CONFIG["speculate"])
    c["speculate"].update({
        "enabled": True,
        "intents": {"A": ['@read "runbook.md" @cache ttl=300']},
    })
    _seed_checkpoints(Path(c["checkpoints"]["store"]), ["A", "B", "A", "B"])

    # No pragma → no speculation pass, no stats file.
    perseus.render_source("@perseus v1\n\nplain text\n", c, ws)
    assert not perseus._speculate_stats_path(c, ws).exists()

    # Pragma → post-render speculation warms the predicted context.
    perseus.render_source(
        "@perseus v1\n\nplain text\n@speculate k=2 budget=500\n", c, ws)
    assert perseus._speculate_stats_path(c, ws).exists()
    probe = perseus._speculate_probe('@read "runbook.md" @cache ttl=300', c, ws)
    assert probe["warm"] is True


# ── budget + confidence gating ────────────────────────────────────────────────

def test_speculation_budget_bound_respected(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "big.md").write_text("word " * 400, encoding="utf-8")   # ~500 tokens
    (ws / "second.md").write_text("tiny", encoding="utf-8")

    c = _mkcfg(tmp_path)
    c["speculate"] = dict(perseus.DEFAULT_CONFIG["speculate"])
    c["speculate"].update({
        "enabled": True,
        "budget_tokens": 10,
        "intents": {"A": [
            '@read "big.md" @cache ttl=300',
            '@read "second.md" @cache ttl=300',
        ]},
    })
    _seed_checkpoints(Path(c["checkpoints"]["store"]), ["A", "B", "A", "B"])

    result = perseus.run_speculation(c, ws)
    statuses = [(e["status"], e.get("reason", "")) for e in result["results"]]
    assert statuses[0][0] == "ran"
    assert statuses[1][0] == "skipped"
    assert "budget exhausted" in statuses[1][1]
    assert result["summary"]["budget_exhausted"] is True
    assert result["summary"]["spent_tokens"] >= 10
    # The over-budget candidate was never warmed.
    probe = perseus._speculate_probe('@read "second.md" @cache ttl=300', c, ws)
    assert probe["warm"] is False


def test_confidence_gating_skips_low_probability_predictions(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "b.md").write_text("bee", encoding="utf-8")
    (ws / "c.md").write_text("sea", encoding="utf-8")

    c = _mkcfg(tmp_path)
    c["speculate"] = dict(perseus.DEFAULT_CONFIG["speculate"])
    c["speculate"].update({
        "enabled": True,
        "confidence_threshold": 0.5,
        "intents": {
            "B": ['@read "b.md" @cache ttl=300'],
            "C": ['@read "c.md" @cache ttl=300'],
        },
    })
    # A→B twice, A→C once; current intent A → p(B)=2/3, p(C)=1/3.
    _seed_checkpoints(Path(c["checkpoints"]["store"]),
                      ["A", "B", "A", "B", "A", "C", "A"])

    result = perseus.run_speculation(c, ws)
    by_intent = {}
    for entry in result["results"]:
        by_intent.setdefault(entry["intent"], []).append(entry)
    assert by_intent["B"][0]["status"] == "ran"
    assert by_intent["C"][0]["status"] == "skipped"
    assert "confidence" in by_intent["C"][0]["reason"]
    assert perseus._speculate_probe('@read "c.md" @cache ttl=300', c, ws)["warm"] is False


# ── hit/miss settlement + stats round-trip ────────────────────────────────────

def test_hit_miss_settlement_and_stats_roundtrip(tmp_path):
    c = _mkcfg(tmp_path)
    c["speculate"] = dict(perseus.DEFAULT_CONFIG["speculate"])
    c["speculate"]["enabled"] = True
    store = Path(c["checkpoints"]["store"])
    _seed_checkpoints(store, ["A", "B", "A", "B"])

    # Run 1: predicts A after current=B. Nothing settled yet.
    r1 = perseus.run_speculation(c, None)
    assert r1["predicted"][0]["intent"] == "A"
    stats = perseus._load_speculate_stats(c, None)
    assert stats["hits"] == 0 and stats["misses"] == 0
    assert stats["pending"]["basis_intent"] == "B"
    assert stats["pending"]["predicted"][0]["intent"] == "A"

    # A real next turn happens: task A. Run 2 settles the prediction: HIT.
    _seed_checkpoints(store, ["A"], start=4)
    r2 = perseus.run_speculation(c, None)
    stats = perseus._load_speculate_stats(c, None)
    assert stats["hits"] == 1 and stats["misses"] == 0
    assert stats["outcomes"][-1]["hit"] is True
    assert stats["outcomes"][-1]["predicted_top1"] == "A"
    assert r2["predicted"][0]["intent"] == "B"  # new pending: A→B

    # Next real turn is C, not B. Run 3 settles: MISS.
    _seed_checkpoints(store, ["C"], start=5)
    perseus.run_speculation(c, None)
    stats = perseus._load_speculate_stats(c, None)
    assert stats["hits"] == 1 and stats["misses"] == 1
    assert len(stats["outcomes"]) == 2
    assert stats["outcomes"][-1] == {
        **stats["outcomes"][-1],
        "predicted_top1": "B", "actual": "C", "hit": False,
    }

    # Round-trip: the on-disk file is valid JSON with the documented shape.
    raw = json.loads(perseus._speculate_stats_path(c, None).read_text(encoding="utf-8"))
    for key in ("version", "workspace", "hits", "misses", "pending",
                "outcomes", "last_run"):
        assert key in raw
    assert raw["version"] == 1
    assert raw["last_run"]["k"] == 3


def test_rerun_without_new_checkpoint_does_not_double_settle(tmp_path):
    c = _mkcfg(tmp_path)
    c["speculate"] = dict(perseus.DEFAULT_CONFIG["speculate"])
    c["speculate"]["enabled"] = True
    _seed_checkpoints(Path(c["checkpoints"]["store"]), ["A", "B", "A", "B"])

    perseus.run_speculation(c, None)
    perseus.run_speculation(c, None)  # same marker → nothing to settle
    stats = perseus._load_speculate_stats(c, None)
    assert stats["hits"] == 0 and stats["misses"] == 0
    assert stats["outcomes"] == []


# ── explain --speculate ───────────────────────────────────────────────────────

def test_explain_speculate_payload_predictions_hit_rate_and_warmth(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "notes.md").write_text("warm me", encoding="utf-8")

    c = _mkcfg(tmp_path)
    c["speculate"] = dict(perseus.DEFAULT_CONFIG["speculate"])
    c["speculate"].update({
        "enabled": True,
        "intents": {"A": ['@read "notes.md" @cache ttl=300']},
    })
    _seed_checkpoints(Path(c["checkpoints"]["store"]), ["A", "B", "A", "B"])

    # Before any speculation pass: candidate is cold, no settled outcomes.
    data = perseus.explain_speculate(c, ws)
    assert data["enabled"] is True
    assert data["current_intent"] == "B"
    assert data["baseline_most_recent"] == "B"
    assert data["predicted"][0]["intent"] == "A"
    assert data["predicted"][0]["probability"] == 1.0
    assert data["predicted"][0]["meets_threshold"] is True
    assert data["predicted"][0]["candidates"][0]["warm"] is False
    assert data["stats"] == {"hits": 0, "misses": 0, "settled": 0, "hit_rate": None}

    # After a speculation pass the candidate shows warm.
    perseus.run_speculation(c, ws)
    data2 = perseus.explain_speculate(c, ws)
    assert data2["predicted"][0]["candidates"][0]["warm"] is True

    # explain is read-only — it must not have recorded a new pending basis.
    human = perseus.format_explain_speculate_human(data2)
    assert "Predicted next intents:" in human
    assert "hit_rate" in human


def test_cmd_explain_requires_speculate_flag():
    args = types.SimpleNamespace(speculate=False, workspace=None, source=None, json=False)
    rc = perseus.cmd_explain(args, cfg())
    assert rc == 2


def test_cmd_explain_speculate_json_inprocess(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)

    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)
    (ws / ".perseus" / "config.yaml").write_text(yaml.dump({
        "speculate": {"enabled": True},
        "checkpoints": {"store": str(tmp_path / "checkpoints")},
        "render": {"cache_dir": str(tmp_path / "cache")},
    }), encoding="utf-8")
    _seed_checkpoints(tmp_path / "checkpoints", ["A", "B", "A", "B"])

    args = types.SimpleNamespace(speculate=True, workspace=str(ws), source=None, json=True)
    data, rc = _capture_json(monkeypatch, perseus.cmd_explain, args, cfg())
    assert rc == 0
    assert data["enabled"] is True
    assert data["predicted"][0]["intent"] == "A"
    assert data["stats"]["settled"] == 0


def test_cli_explain_speculate_subprocess(tmp_path):
    """End-to-end: parser block + dispatch wire `perseus explain --speculate`."""
    home = tmp_path / "home"
    home.mkdir()
    ws = tmp_path / "ws"
    (ws / ".perseus").mkdir(parents=True)
    (ws / ".perseus" / "config.yaml").write_text(yaml.dump({
        "speculate": {"enabled": True},
        "checkpoints": {"store": str(tmp_path / "checkpoints")},
        "render": {"cache_dir": str(tmp_path / "cache")},
    }), encoding="utf-8")
    _seed_checkpoints(tmp_path / "checkpoints", ["A", "B", "A", "B"])

    env = dict(os.environ)
    env["PERSEUS_HOME"] = str(home)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "perseus.py"), "explain", "--speculate",
         "--json", "--workspace", str(ws)],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["enabled"] is True
    assert data["predicted"][0]["intent"] == "A"


# ── workspace scoping of the stats file ───────────────────────────────────────

def test_stats_file_is_workspace_keyed(tmp_path):
    c = _mkcfg(tmp_path)
    ws_a = tmp_path / "wsA"
    ws_b = tmp_path / "wsB"
    ws_a.mkdir()
    ws_b.mkdir()
    p_a = perseus._speculate_stats_path(c, ws_a)
    p_b = perseus._speculate_stats_path(c, ws_b)
    p_global = perseus._speculate_stats_path(c, None)
    assert p_a != p_b != p_global
    assert p_a.name.startswith("speculate_stats-")
    assert p_global.name == "speculate_stats-global.json"


# ── #636: bounded history parsing + one shared store listing ─────────────────

def test_intent_history_identical_and_parses_at_most_window_files(tmp_path, monkeypatch):
    """#636: windowed history must (a) equal the old parse-everything-then-
    slice result exactly, and (b) parse at most `window` checkpoint files."""
    c = _mkcfg(tmp_path)
    tasks = [f"T{i % 5}" for i in range(50)]
    _seed_checkpoints(Path(c["checkpoints"]["store"]), tasks)

    # (a) decisions identical: windowed == unbounded result sliced afterwards.
    full = perseus._speculate_intent_history(c, None, 0)
    assert full == tasks
    windowed = perseus._speculate_intent_history(c, None, 10)
    assert windowed == full[-10:]

    # (b) bounded work: only the newest `window` files are opened/parsed.
    real_load = perseus._load_checkpoint_file
    calls = {"n": 0}

    def _counting(fp):
        calls["n"] += 1
        return real_load(fp)

    monkeypatch.setattr(perseus, "_load_checkpoint_file", _counting)
    assert perseus._speculate_intent_history(c, None, 10) == windowed
    assert calls["n"] == 10, (
        f"parsed {calls['n']} checkpoint files for a window of 10 "
        "(pre-#636: the whole store, every opted-in render)")


def test_run_speculation_lists_checkpoint_store_once(tmp_path, monkeypatch):
    """#636: history and the settlement marker must share ONE store listing."""
    c = _mkcfg(tmp_path)
    c["speculate"] = {"enabled": True}
    _seed_checkpoints(Path(c["checkpoints"]["store"]), ["A", "B", "A", "B"])
    real_list = perseus._list_checkpoint_files
    calls = {"n": 0}

    def _counting(cfg_):
        calls["n"] += 1
        return real_list(cfg_)

    monkeypatch.setattr(perseus, "_list_checkpoint_files", _counting)
    out = perseus.run_speculation(c, None)
    assert out["enabled"] is True
    assert out["predicted"], "sanity: the pass must still predict"
    assert calls["n"] == 1, f"store listed {calls['n']}x per speculation pass"
