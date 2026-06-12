# Perseus container image — MCP server, minimal single-file runtime.
#
# Build:  docker build -t perseus:local .
# Verify: docker run --rm perseus:local mcp serve (starts MCP server over stdio)
#
# Perseus depends only on pyyaml + Python 3.10+ stdlib.
# The single-file perseus.py is the entire runtime, copied directly
# into the image and installed as the `perseus` entrypoint.

FROM python:3.12-slim

LABEL org.opencontainers.image.title="Perseus MCP Server"
LABEL org.opencontainers.image.description="MCP server and live context engine for AI assistants — 25 tools, resolver-first, assistant-agnostic"
LABEL org.opencontainers.image.source="https://github.com/tcconnally/perseus"
LABEL org.opencontainers.image.version="1.0.7"

# Copy requirements and install the single dependency
COPY requirements.txt /tmp/perseus-requirements.txt
RUN pip install --no-cache-dir -r /tmp/perseus-requirements.txt && \
    rm /tmp/perseus-requirements.txt && \
    mkdir -p /perseus-home /workspace

# Copy the single-file runtime
COPY perseus.py /usr/local/lib/perseus/perseus.py

# Symlink for easy invocation
RUN ln -s /usr/local/lib/perseus/perseus.py /usr/local/bin/perseus && \
    chmod +x /usr/local/lib/perseus/perseus.py

ENV PERSEUS_HOME=/perseus-home
ENV PYTHONUNBUFFERED=1

WORKDIR /workspace

ENTRYPOINT ["perseus"]
CMD ["mcp", "serve"]
