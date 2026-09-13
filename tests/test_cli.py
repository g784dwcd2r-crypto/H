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
