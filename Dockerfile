FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        tesseract-ocr \
        tesseract-ocr-eng \
        poppler-utils \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md requirements.txt ./
COPY src ./src
COPY docs ./docs
COPY config ./config
COPY scripts ./scripts

RUN python -m pip install --upgrade pip \
    && python -m pip install -e '.[aws]'

RUN mkdir -p /data/corpora /data/truth /data/runs /data/logs /data/cache

CMD ["dupe-engine", "doctor"]
