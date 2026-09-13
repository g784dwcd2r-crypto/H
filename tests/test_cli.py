from typer.testing import CliRunner

from filings_hub.cli import app
from filings_hub.config import reset_settings_cache

runner = CliRunner()


def test_cli_demo_export_quality_golden(tmp_path, monkeypatch):
    monkeypatch.setenv("LAKE_ROOT", str(tmp_path / "lake"))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SEC_USER_AGENT", "Test test@example.com")
    monkeypatch.chdir(tmp_path)
    reset_settings_cache()
    r = runner.invoke(app, ["demo"])
    assert r.exit_code == 0, r.output
    assert "[backfill] ok" in r.output
    r = runner.invoke(app, ["export", "AAPL", "--periods", "FY2025,Q1 2026", "--out", str(tmp_path / "a.xlsx")])
    assert r.exit_code == 0 and (tmp_path / "a.xlsx").stat().st_size > 5000
    r = runner.invoke(app, ["export", "320193"])
    assert r.exit_code == 0 and (tmp_path / "320193-statements.xlsx").exists()
    r = runner.invoke(app, ["metrics"])
    assert r.exit_code == 0 and "company_metrics:" in r.output, r.output

    import httpx

    from filings_hub.ingest import edgar_client as ec
    from filings_hub.lake import layout
    from filings_hub.lake.storage import Storage
    from filings_hub.testing import edgar_fixtures as fx

    monkeypatch.setattr(
        ec,
        "client_from_settings",
        lambda **kw: ec.EdgarClient("Test test@example.com", transport=httpx.MockTransport(fx.edgar_document_handler)),
    )
    r = runner.invoke(app, ["documents", "--tickers", "AAPL", "--periods", "2"])
    assert r.exit_code == 0 and "1/1 companies" in r.output, r.output
    assert Storage(str(tmp_path / "lake")).exists(f"{layout.documents_cik_dir(fx.APPLE)}/part-0.parquet")
    assert runner.invoke(app, ["export", "NOPE"]).exit_code == 2
    (tmp_path / "t.txt").write_text("AAPL\nJPM\n")
    r = runner.invoke(app, ["quality", "--since", "2024", "--tickers-file", str(tmp_path / "t.txt")])
    assert r.exit_code == 0 and "overall pass rate: 100.0%" in r.output
    r = runner.invoke(app, ["golden", "AAPL,19617,ZZZZ"])
    assert r.exit_code == 0 and "Apple Inc. (AAPL) FYE 0927" in r.output and "ZZZZ: unknown" in r.output
    r = runner.invoke(app, ["load"])
    assert r.exit_code == 2  # no DATABASE_URL
    reset_settings_cache()


def test_api_command_honours_port_env(monkeypatch):
    """Render and friends hand the listening port over as $PORT."""
    seen: dict = {}

    def fake_run(*a, **kw):
        seen.update(kw)

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setenv("PORT", "10000")
    assert runner.invoke(app, ["api"]).exit_code == 0 and seen["port"] == 10000
    assert runner.invoke(app, ["api", "--port", "8001"]).exit_code == 0 and seen["port"] == 8001
    monkeypatch.delenv("PORT")
    assert runner.invoke(app, ["api"]).exit_code == 0 and seen["port"] == 8000


def test_compact_filings_sorts_each_year_into_small_row_groups(lake_copy):
    import pyarrow.parquet as pq

    from filings_hub.ingest.sync_filings import FILINGS_ROW_GROUP, compact_filings
    from filings_hub.lake import layout
    from filings_hub.lake.storage import Storage

    storage: Storage = lake_copy
    before = sum(pq.read_metadata(storage.full(f)).num_rows for f in storage.glob(f"{layout.FILINGS}/*/*.parquet"))
    done = compact_filings(storage)
    assert done and sum(done.values()) == before
    for year, n in done.items():
        files = storage.glob(f"{layout.filings_year_dir(year)}/*.parquet")
        assert len(files) == 1
        meta = pq.read_metadata(storage.full(files[0]))
        assert meta.num_rows == n
        assert all(meta.row_group(i).num_rows <= FILINGS_ROW_GROUP for i in range(meta.num_row_groups))
        ciks = pq.read_table(storage.full(files[0]), columns=["cik"]).column("cik").to_pylist()
        assert ciks == sorted(ciks)  # a company's rows sit together: the reader skips the other row groups


def test_cli_compact(tmp_path, monkeypatch):
    monkeypatch.setenv("LAKE_ROOT", str(tmp_path / "lake"))
    monkeypatch.setenv("DATABASE_URL", "")
    reset_settings_cache()
    assert runner.invoke(app, ["demo"]).exit_code == 0
    r = runner.invoke(app, ["compact"])
    assert r.exit_code == 0, r.output
    assert "compacted" in r.output and "filings" in r.output
