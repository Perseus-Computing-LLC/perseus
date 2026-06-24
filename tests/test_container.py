"""Container image and compose smoke checks (task-55 / Phase 20B)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = REPO_ROOT / "Dockerfile"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yaml"
CONTAINER_CONFIG = REPO_ROOT / "examples" / "container" / "config.yaml"
CONTAINER_DOC = REPO_ROOT / "docs" / "CONTAINER.md"


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)


def test_container_files_are_present():
    assert DOCKERFILE.exists(), "Dockerfile missing"
    assert COMPOSE_FILE.exists(), "docker-compose.yaml missing"
    assert CONTAINER_CONFIG.exists(), "container auth config example missing"
    assert CONTAINER_DOC.exists(), "docs/CONTAINER.md missing"


def test_dockerfile_uses_single_file_runtime():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY perseus.py /usr/local/bin/perseus" in text
    assert "COPY . " not in text
    assert 'ENTRYPOINT ["perseus"]' in text
    assert "pip install --no-cache-dir -r /tmp/requirements.txt" in text
    assert "PERSEUS_HOME=/perseus-home" in text


def test_compose_declares_render_and_authenticated_serve():
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    services = compose["services"]

    render = services["render"]
    assert render["command"] == [
        "render",
        "/workspace/.perseus/context.md",
        "--output",
        "/perseus-home/rendered-context.md",
    ]
    assert "./:/workspace:ro" in render["volumes"]

    serve = services["serve"]
    assert "serve" in serve["profiles"]
    assert "127.0.0.1:7991:7991" in serve["ports"]
    assert "./examples/container/config.yaml:/perseus-home/config.yaml:ro" in serve["volumes"]
    assert serve["command"] == [
        "serve",
        "--host",
        "0.0.0.0",
        "--port",
        "7991",
        "--workspace",
        "/workspace",
    ]


def test_container_auth_config_is_explicit_placeholder():
    cfg = yaml.safe_load(CONTAINER_CONFIG.read_text(encoding="utf-8"))
    assert cfg["serve"]["bind_host"] == "0.0.0.0"
    assert cfg["serve"]["auth_token"] == "change-me-before-serving"
    assert "Replace this token" in CONTAINER_CONFIG.read_text(encoding="utf-8")


def test_container_docs_cover_trust_and_read_only_mounts():
    text = CONTAINER_DOC.read_text(encoding="utf-8")
    for needle in [
        "single-file runtime",
        "read-only",
        "Authorization: Bearer",
        "Do not mount the host container socket",
        "PERSEUS_HOME=/perseus-home",
    ]:
        assert needle in text


def test_docker_image_reports_version_when_docker_is_available():
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker CLI not available")

    info = _run([docker, "info"], timeout=20)
    if info.returncode != 0:
        pytest.skip(f"docker daemon not available: {info.stderr.strip() or info.stdout.strip()}")

    tag = f"perseus-test:{os.getpid()}"
    build = _run([docker, "build", "-t", tag, str(REPO_ROOT)], timeout=180)
    assert build.returncode == 0, f"docker build failed:\n{build.stdout}\n{build.stderr}"
    try:
        out = _run([docker, "run", "--rm", tag, "--version"], timeout=30)
        assert out.returncode == 0, f"docker run failed:\n{out.stdout}\n{out.stderr}"
        assert out.stdout.startswith("perseus v")
    finally:
        _run([docker, "image", "rm", "-f", tag], timeout=30)
