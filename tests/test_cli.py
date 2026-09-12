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
    assert runner.invoke(app, ["export", "NOPE"]).exit_code == 2
    (tmp_path / "t.txt").write_text("AAPL\nJPM\n")
    r = runner.invoke(app, ["quality", "--since", "2024", "--tickers-file", str(tmp_path / "t.txt")])
    assert r.exit_code == 0 and "overall pass rate: 100.0%" in r.output
    r = runner.invoke(app, ["golden", "AAPL,19617,ZZZZ"])
    assert r.exit_code == 0 and "Apple Inc. (AAPL) FYE 0927" in r.output and "ZZZZ: unknown" in r.output
    r = runner.invoke(app, ["load"])
    assert r.exit_code == 2  # no DATABASE_URL
    reset_settings_cache()
