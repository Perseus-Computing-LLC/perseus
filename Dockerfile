# syntax=docker/dockerfile:1

FROM python:3.12-slim

LABEL org.opencontainers.image.title="Perseus"
LABEL org.opencontainers.image.description="Single-file Perseus context engine runtime"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PERSEUS_HOME=/perseus-home

RUN useradd --create-home --home-dir /perseus-home --shell /usr/sbin/nologin --uid 10001 perseus \
    && mkdir -p /workspace /usr/local/lib/perseus \
    && chown -R perseus:perseus /perseus-home /workspace /usr/local/lib/perseus

COPY requirements.txt /tmp/perseus-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/perseus-requirements.txt \
    && rm -f /tmp/perseus-requirements.txt

COPY perseus.py /usr/local/lib/perseus/perseus.py
RUN chmod 0755 /usr/local/lib/perseus/perseus.py \
    && ln -s /usr/local/lib/perseus/perseus.py /usr/local/bin/perseus

USER perseus
WORKDIR /workspace
VOLUME ["/workspace", "/perseus-home"]
EXPOSE 7991

ENTRYPOINT ["perseus"]
CMD ["--help"]
