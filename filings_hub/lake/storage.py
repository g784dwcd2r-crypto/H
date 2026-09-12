"""Thin storage layer over fsspec so the lake can live on local disk or S3 with one code path."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import fsspec
import pyarrow as pa
import pyarrow.parquet as pq


def filesystem_for(root: str) -> fsspec.AbstractFileSystem:
    """The fsspec filesystem for a remote lake root, configured from settings (credentials, region,
    and an optional S3-compatible endpoint). Worker processes rebuild it the same way from the env."""
    protocol = root.split("://", 1)[0]
    if protocol in ("s3", "s3a"):
        from filings_hub.config import get_settings

        return fsspec.filesystem("s3", **get_settings().s3_storage_options())
    fs, _ = fsspec.core.url_to_fs(root)
    return fs


class Storage:
    """All paths passed to methods are *relative to the lake root*.

    `root` may be a local directory (``./data``) or an S3 prefix (``s3://bucket/prefix``).
    """

    def __init__(self, root: str, fs: fsspec.AbstractFileSystem | None = None):
        root = root.rstrip("/")
        self.is_remote = "://" in root
        self.root = root
        if self.is_remote:
            self.fs = fs or filesystem_for(root)
        else:
            self.fs = fsspec.filesystem("file")
            self.root = str(Path(root).resolve())
            Path(self.root).mkdir(parents=True, exist_ok=True)

    # -- paths ---------------------------------------------------------------------------------
    def full(self, rel: str) -> str:
        return f"{self.root}/{rel.strip('/')}" if rel else self.root

    def duck_path(self, rel: str) -> str:
        """Path usable inside DuckDB SQL (s3:// or absolute local)."""
        return self.full(rel)

    # -- basic ops -----------------------------------------------------------------------------
    def exists(self, rel: str) -> bool:
        return self.fs.exists(self.full(rel))

    def ls(self, rel: str) -> list[str]:
        """List entries in a directory as lake-relative paths (empty if dir missing)."""
        full = self.full(rel)
        if not self.fs.exists(full):
            return []
        out = []
        for entry in self.fs.ls(full, detail=False):
            entry = str(entry)
            out.append(self._relativise(entry))
        return sorted(out)

    def glob(self, pattern: str) -> list[str]:
        return sorted(self._relativise(str(p)) for p in self.fs.glob(self.full(pattern)))

    def _relativise(self, full_path: str) -> str:
        norm_root = self.root.split("://", 1)[-1] if self.is_remote else self.root
        p = full_path.split("://", 1)[-1] if "://" in full_path else full_path
        if p.startswith(norm_root):
            return p[len(norm_root) :].lstrip("/")
        return p

    def size(self, rel: str) -> int:
        return int(self.fs.size(self.full(rel)))

    def mkdirs(self, rel: str) -> None:
        if not self.is_remote:
            Path(self.full(rel)).mkdir(parents=True, exist_ok=True)

    def delete(self, rel: str) -> None:
        full = self.full(rel)
        if self.fs.exists(full):
            self.fs.rm(full, recursive=True)

    def read_bytes(self, rel: str) -> bytes:
        with self.fs.open(self.full(rel), "rb") as f:
            return f.read()

    def read_text(self, rel: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(rel).decode(encoding, errors="replace")

    def write_bytes(self, rel: str, data: bytes) -> None:
        self.mkdirs(os.path.dirname(rel))
        with self.fs.open(self.full(rel), "wb") as f:
            f.write(data)

    def write_text(self, rel: str, text: str) -> None:
        self.write_bytes(rel, text.encode("utf-8"))

    @contextmanager
    def open(self, rel: str, mode: str = "rb") -> Iterator:
        if "w" in mode:
            self.mkdirs(os.path.dirname(rel))
        with self.fs.open(self.full(rel), mode) as f:
            yield f

    @contextmanager
    def local_copy(self, rel: str) -> Iterator[Path]:
        """Yield a local filesystem path for `rel` (a temp download when the lake is remote)."""
        if not self.is_remote:
            yield Path(self.full(rel))
            return
        tmpdir = tempfile.mkdtemp(prefix="filings-hub-")
        try:
            local = Path(tmpdir) / os.path.basename(rel)
            self.fs.get(self.full(rel), str(local))
            yield local
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # -- parquet -------------------------------------------------------------------------------
    def write_parquet(self, rel: str, table: pa.Table) -> None:
        self.mkdirs(os.path.dirname(rel))
        with self.fs.open(self.full(rel), "wb") as f:
            pq.write_table(table, f, compression="zstd")

    def read_parquet(self, rel: str) -> pa.Table:
        with self.fs.open(self.full(rel), "rb") as f:
            return pq.read_table(f)

    def replace_dir_with_parquet(self, rel_dir: str, table: pa.Table, name: str = "part-0.parquet") -> None:
        """Atomically-enough replace a partition directory with a single parquet file."""
        self.delete(rel_dir)
        self.write_parquet(f"{rel_dir}/{name}", table)
