FROM python:3.12-slim

WORKDIR /workspace
COPY perseus.py /usr/local/bin/perseus
# Runtime-only deps (PyYAML). NOT the full dev/CI freeze in requirements.txt —
# the container ships the runtime, not the toolchain. This also avoids needing
# git in the image (the dev freeze pulls an editable git VCS dependency).
COPY requirements-runtime.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && chmod +x /usr/local/bin/perseus

ENV PERSEUS_HOME=/perseus-home
ENV PYTHONUNBUFFERED=1
# NOTE: PERSEUS_ALLOW_DANGEROUS is intentionally NOT set here. It is the master
# gate for shell-executing directives (@query/@agent/@services command:) and is
# meant to be an explicit, per-deployment opt-in. Baking it into the published
# image would silently remove one of the two required gate layers for every
# container. Operators who need it must pass `-e PERSEUS_ALLOW_DANGEROUS=1` at
# `docker run` time (and also enable the matching `render.allow_*_shell` config).

# Run as a non-root user. The MCP server parses untrusted context/memory content;
# there is no reason for it to hold root in-container.
RUN useradd --create-home --uid 10001 perseus \
    && mkdir -p /perseus-home /workspace \
    && chown -R perseus:perseus /perseus-home /workspace
USER perseus

ENTRYPOINT ["perseus"]
CMD ["mcp", "serve"]
