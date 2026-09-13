FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
COPY filings_hub ./filings_hub
RUN uv sync --frozen --no-dev --extra s3
ENV PATH="/app/.venv/bin:$PATH"
ENV LAKE_ROOT=/data
VOLUME ["/data"]
EXPOSE 8000
CMD ["filings-hub", "api"]
