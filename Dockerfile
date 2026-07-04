# rivenforge headless API — Linux container.
#
# Serves the cross-platform half of rivenforge: rules engine, RAG scoring,
# config, weapon lookup, and MANUAL-OCR analysis (paste stat lines). Live
# screen/window capture and image OCR are Windows-only (winocr / dxcam /
# Windows.Graphics.Capture) and are NOT available in this image — those
# endpoints return a clear error. See PACKAGING.md.
#
# Build:  docker build -t rivenforge-api .
# Run:    docker run --rm -p 47321:47321 rivenforge-api
# Health: curl http://localhost:47321/health

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install only the headless-API dependency subset first for layer caching.
COPY requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt

# Copy the application code needed at runtime. The frontend, Tauri shell,
# tests, build artifacts, and debug images are excluded via .dockerignore.
COPY api ./api
COPY core ./core
COPY rag ./rag
COPY data ./data
COPY config ./config
COPY data_util.py api_sidecar.py ./

# The sidecar binds to 127.0.0.1 by default; in a container it must listen on
# all interfaces so the mapped port is reachable from the host.
EXPOSE 47321
CMD ["python", "api_sidecar.py", "--host", "0.0.0.0", "--port", "47321", "--log-level", "info"]
