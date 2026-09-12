FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
COPY filings_hub ./filings_hub
RUN uv pip install --system --no-cache ".[s3]"
ENV LAKE_ROOT=/data
VOLUME ["/data"]
EXPOSE 8000
CMD ["filings-hub", "api"]
