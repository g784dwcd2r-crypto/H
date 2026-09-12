"""Lake: Parquet layout on local disk or S3, queried with DuckDB."""

from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage

__all__ = ["Duck", "Storage"]
