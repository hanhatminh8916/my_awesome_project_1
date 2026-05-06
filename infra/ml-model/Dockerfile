# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — build: install Python deps into a virtual-env
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS build

WORKDIR /app

RUN pip install --no-cache-dir virtualenv && \
    python -m virtualenv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — runtime
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Non-root user
RUN useradd --system --uid 10001 mluser

WORKDIR /app

COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code and pre-trained models (baked in at build time)
COPY serve.py .
COPY models/ ./models/

RUN chown -R mluser:mluser /app

USER mluser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "serve:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
