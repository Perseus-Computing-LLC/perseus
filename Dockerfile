FROM python:3.12-slim

WORKDIR /workspace
COPY perseus.py /usr/local/bin/perseus
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && chmod +x /usr/local/bin/perseus

ENV PERSEUS_HOME=/perseus-home
ENV PYTHONUNBUFFERED=1
ENV PERSEUS_ALLOW_DANGEROUS=1

ENTRYPOINT ["perseus"]
CMD ["mcp", "serve"]
