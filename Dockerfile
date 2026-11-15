# API + background worker in one container (Railway; any Docker host works the same way).
# The two share the uploaded originals on one disk, so they run side by side here.
#
#   build:  the Python dependencies, then the two local models (downloaded at build time so a
#           start never fetches ~1.2 GB), then the code (a code change rebuilds only that layer)
#   start:  scripts/start_service.sh  (migrations, worker, API on $PORT)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed

# libmagic: file-type detection (python-magic)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies only (from pyproject.toml), so code changes reuse this layer.
COPY pyproject.toml ./
RUN python -c "import tomllib; d = tomllib.load(open('pyproject.toml', 'rb')); print('\n'.join(d['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

# The embedding model and the reranker, baked into the image.
RUN python -c "from fastembed import TextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; TextEmbedding('BAAI/bge-small-en-v1.5'); TextCrossEncoder('BAAI/bge-reranker-base'); print('models ready')"

# The code and what it reads at run time. The app runs from /app (paths are relative to it).
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY plugins ./plugins
COPY scripts ./scripts
COPY data/raw ./data/raw
COPY data/ops ./data/ops
COPY synthetic ./synthetic
COPY deploy ./deploy

# Windows checkouts may give the start script CRLF line endings; bash needs LF.
RUN sed -i 's/\r$//' scripts/start_service.sh && chmod +x scripts/start_service.sh

EXPOSE 8000
CMD ["bash", "scripts/start_service.sh"]
