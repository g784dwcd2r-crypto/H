"""Runtime configuration, loaded from the environment / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    sec_user_agent: str = Field(
        default="",
        description='Required by SEC fair-access policy, e.g. "Filings Hub you@example.com".',
    )
    lake_root: str = Field(default="./data", description="Local dir or s3://bucket/prefix.")
    s3_bucket: str = Field(default="", description="Legacy alias; used when lake_root is unset.")
    database_url: str = Field(default="", description="postgresql://... ; empty = serve from lake.")

    slack_webhook_url: str = ""
    alert_email_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    api_key: str = ""
    api_rate_limit_per_minute: int = 60

    edgar_requests_per_second: float = 10.0
    edgar_max_retries: int = 5
    edgar_timeout_seconds: float = 60.0
    # SEC throttling (HTTP 403/429) blocks an IP for ~10 minutes; these rounds wait it out (30 s doubling to the cap).
    edgar_throttle_retries: int = 8
    edgar_throttle_max_wait_seconds: float = 600.0

    # AWS credentials for DuckDB httpfs when the lake is on S3 (also read by s3fs from env).
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""
    aws_region: str = "us-east-1"

    @field_validator("lake_root", mode="before")
    @classmethod
    def _default_lake_root(cls, v: str | None) -> str:
        return v or "./data"

    def resolved_lake_root(self) -> str:
        if self.lake_root and self.lake_root != "./data":
            return self.lake_root
        if self.s3_bucket:
            return f"s3://{self.s3_bucket}/filings-hub"
        return self.lake_root


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
