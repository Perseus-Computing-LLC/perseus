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
ENV PERSEUS_ALLOW_DANGEROUS=1

ENTRYPOINT ["perseus"]
CMD ["mcp", "serve"]
