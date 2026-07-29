# =============================================================================
# Dockerfile — Browser Helper Proxy
#
# Build and runtime in one stage.  Layer ordering maximises cache reuse:
#   1. system packages (seldom change)
#   2. pip upgrade + pyproject.toml → pip install (deps cached by checksum)
#   3. source code (changes most frequently)
# =============================================================================

FROM python:3.11-slim

# ---------------------------------------------------------------------------
# Metadata (must be early so they survive copy steps)
# ---------------------------------------------------------------------------
LABEL org.opencontainers.image.title="Browser Helper Proxy"
LABEL org.opencontainers.image.description="Remote Chrome control proxy with REST API + GUI dashboard"
LABEL org.opencontainers.image.version="1.4.0"

# Disable Python bytecode writes inside the container (saves space, no
# __pycache__ dirt at runtime).  Devs can still build bytecode on their host.
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# ---------------------------------------------------------------------------
# Layer 1 — system dependencies
# ---------------------------------------------------------------------------
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Layer 2 — Python dependencies (cached by pyproject.toml hash)
# ---------------------------------------------------------------------------
COPY pyproject.toml ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[dev]"

# ---------------------------------------------------------------------------
# Layer 3 — application source & static files
# ---------------------------------------------------------------------------
COPY src/ ./src/
COPY static/ ./static/
COPY tests/ ./tests/

# Add src/ to PYTHONPATH so `from cdp_client import CDPClient` (used by
# main.py) resolves correctly without modifying Python source files.
ENV PYTHONPATH=/app/src

# ---------------------------------------------------------------------------
# Security: drop root privileges
# ---------------------------------------------------------------------------
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Healthcheck: /status returns HTTP 200 regardless of Chrome CDP state,
# so this tests the server process, not the CDP link.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; r = urllib.request.urlopen('http://localhost:8000/status'); assert r.status == 200" || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
