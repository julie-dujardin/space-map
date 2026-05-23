FROM ghcr.io/astral-sh/uv:bookworm-slim AS builder

# uv reads requires-python from data/pyproject.toml and installs the matching
# interpreter at sync time, so Python version is driven by pyproject — no ARG.
ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_INSTALL_DIR=/python \
    UV_PROJECT_ENVIRONMENT=/app/data/.venv \
    PATH=/app/data/.venv/bin:$PATH

# openexr has no cp314 wheels; uv builds it from sdist via scikit-build-core,
# which needs cmake + a C/C++ toolchain + git (CMake FetchContent clones Imath).
# Build deps stay in this stage only.
RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake build-essential git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/data

# Install deps first against the lockfile so the layer caches across source-only edits.
COPY data/pyproject.toml data/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Then add the source and install the project itself. uv installs in editable
# mode, so paths.py is in /app/data/src/... — DATA_DIR=/app/data,
# PROJECT_ROOT=/app, DOWNLOAD_DIR=/space-map-downloads (the bind-mount target).
COPY data/ ./
RUN uv sync --frozen --no-dev

FROM ghcr.io/astral-sh/uv:bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_PYTHON_INSTALL_DIR=/python \
    UV_PROJECT_ENVIRONMENT=/app/data/.venv \
    PATH=/app/data/.venv/bin:$PATH

WORKDIR /app/data

COPY --from=builder /python /python
COPY --from=builder /app/data /app/data

CMD ["space-map-scheduler"]
