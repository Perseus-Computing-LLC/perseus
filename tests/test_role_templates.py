import argparse

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

# ───────────────────── #512 — founders / devops / research role templates ─────

ROLE_TEMPLATES = ["founders", "devops", "research"]

# Role-specific directives that must survive into each rendered context.md.
ROLE_DIRECTIVES = {
    "founders": ["@prompt", "@date", "@waypoint", "@agora", "@memory", "@health", "@read", "@query"],
    "devops": ["@prompt", "@services", "@query", "@read", "@health", "@tooltrim", "@agora"],
    "research": ["@prompt", "@memory", "@include", "@read", "@agora", "@session", "@waypoint"],
}


# ── _list_templates() discovers the new role templates ───────────────────────

def test_list_templates_includes_role_templates():
    templates = perseus._list_templates()
    for name in ROLE_TEMPLATES:
        assert name in templates, f"{name} missing from _list_templates(): {templates}"


@pytest.mark.parametrize("name", ROLE_TEMPLATES)
def test_load_template_returns_content(name):
    content = perseus._load_template(name)
    assert content is not None
    assert content.lstrip().startswith("@perseus")


# ── init --template <name> writes a context.md starting with @perseus ─────────

@pytest.mark.parametrize("name", ROLE_TEMPLATES)
def test_init_template_writes_context_starting_with_perseus(tmp_path, capsys, name):
    args = argparse.Namespace(workspace=str(tmp_path), force=False,
                              template=name, list_templates=False)
    perseus.cmd_init(args, cfg())
    capsys.readouterr()
    ctx = tmp_path / ".perseus" / "context.md"
    assert ctx.exists()
    body = ctx.read_text()
    assert body.lstrip().startswith("@perseus")


# ── role-specific directives present; no unsubstituted {workspace} ───────────

@pytest.mark.parametrize("name", ROLE_TEMPLATES)
def test_init_template_substitutes_workspace_and_has_directives(tmp_path, capsys, name):
    args = argparse.Namespace(workspace=str(tmp_path), force=False,
                              template=name, list_templates=False)
    perseus.cmd_init(args, cfg())
    capsys.readouterr()
    body = (tmp_path / ".perseus" / "context.md").read_text()

    # {workspace} must be fully substituted with the real path.
    assert "{workspace}" not in body
    assert str(tmp_path) in body

    for directive in ROLE_DIRECTIVES[name]:
        assert directive in body, f"{directive} missing from {name} template"


# ── render smoke test: each template renders without raising ─────────────────

@pytest.mark.parametrize("name", ROLE_TEMPLATES)
def test_template_renders_without_traceback(tmp_path, name):
    content = perseus._load_template(name).replace("{workspace}", str(tmp_path))
    # Should resolve all directives (degrading to warnings as needed) and never raise.
    rendered = perseus.render_source(content, cfg(), tmp_path)
    assert isinstance(rendered, str)
    assert rendered.strip()
