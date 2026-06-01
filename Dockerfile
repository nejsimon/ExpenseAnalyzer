# Stage 1 — builder: install dependencies into an in-project venv
FROM python:3.13-slim AS builder
WORKDIR /app

RUN pip install uv --no-cache-dir

COPY pyproject.toml uv.lock ./
# Install only dependencies (skip installing the package itself — source is copied in runtime stage)
RUN uv sync --extra ui --no-dev --frozen --no-install-project

# Stage 2 — runtime: copy venv + source only (no uv, no build tools)
FROM python:3.13-slim
WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY expense_analyzer/ expense_analyzer/

ENV PATH="/app/.venv/bin:$PATH"
ENV EXPENSE_ANALYZER_DB=/data/expense-analyzer.db

RUN mkdir /data
VOLUME /data
EXPOSE 8501

CMD ["streamlit", "run", "expense_analyzer/ui.py", \
     "--server.port=8501", "--server.address=0.0.0.0"]
