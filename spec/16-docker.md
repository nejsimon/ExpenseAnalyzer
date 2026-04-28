# 16 — Dockerfile

**Status:** [x] done

## Description

Package the Streamlit UI (spec 14) in a Docker image for easy deployment. Multi-stage build keeps the final image small: a builder stage installs dependencies, the runtime stage copies only the virtual environment and application source.

## Acceptance Criteria

- `docker build -t utgiftsanalys .` succeeds from the repo root.
- `docker run -p 8501:8501 -v $PWD/data:/data utgiftsanalys` starts the Streamlit UI at `http://localhost:8501`.
- The final image is based on `python:3.13-slim` (Debian/apt-based) and contains no uv, no build tools, no dev dependencies, no test files.
- The SQLite database persists across container restarts when `/data` is bind-mounted.
- A `.dockerignore` prevents unnecessary files from entering the build context.

## Dockerfile (multi-stage)

```dockerfile
# Stage 1 — builder
FROM python:3.13-slim AS builder
WORKDIR /app

RUN pip install uv --no-cache-dir

COPY pyproject.toml uv.lock ./
# Install only the ui extra (no dev deps) into an in-project venv
RUN uv sync --extra ui --no-dev --frozen

# Stage 2 — runtime
FROM python:3.13-slim
WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY utgiftsanalys/ utgiftsanalys/

ENV PATH="/app/.venv/bin:$PATH"
ENV UTGIFTSANALYS_DB=/data/utgiftsanalys.db

RUN mkdir /data
VOLUME /data
EXPOSE 8501

CMD ["streamlit", "run", "utgiftsanalys/ui.py", \
     "--server.port=8501", "--server.address=0.0.0.0"]
```

## .dockerignore

```
.venv/
data/
tests/
spec/
__pycache__/
*.pyc
.git/
.gitignore
```

## Implementation Notes

- `uv sync --frozen` uses `uv.lock` to pin exact versions — reproducible builds.
- The `--extra ui` flag pulls in `streamlit` and `altair` without `fastapi` or `pytest`.
- `VOLUME /data` declares the mount point; users bind-mount with `-v $PWD/data:/data`.
- Streamlit requires `--server.address=0.0.0.0` to be reachable outside the container.
- `python:3.13-slim` is Debian-based; apt is available if extra system packages are ever needed.
