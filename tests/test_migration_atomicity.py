import psycopg
import pytest
from typer.testing import CliRunner

from filings_hub.cli import app
from filings_hub.config import reset_settings_cache
from filings_hub.db import load


def test_migration_failure_rolls_back_ddl_and_tracking(pg_url, tmp_path, monkeypatch):
    with psycopg.connect(pg_url, autocommit=True) as conn:
        load.apply_migrations(conn)
        (tmp_path / "9999_injected.sql").write_text("CREATE TABLE should_rollback (id INTEGER); SELECT no_such_column;")
        monkeypatch.setattr(load, "MIGRATIONS_DIR", tmp_path)
        with pytest.raises(psycopg.errors.UndefinedColumn):
            load.apply_migrations(conn)
        assert conn.execute("SELECT to_regclass('should_rollback')").fetchone()[0] is None
        assert conn.execute("SELECT count(*) FROM schema_migrations WHERE name='9999_injected.sql'").fetchone()[0] == 0


def test_migrate_command_is_repeatable_and_does_not_reload_companies(pg_url, built_lake, monkeypatch):
    load.load_full(built_lake, pg_url)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        before = conn.execute("SELECT count(*) FROM companies").fetchone()[0]
    monkeypatch.setenv("DATABASE_URL", pg_url)
    reset_settings_cache()
    try:
        result = CliRunner().invoke(app, ["migrate"])
        assert result.exit_code == 0 and "schema already current" in result.output
        with psycopg.connect(pg_url) as conn:
            assert conn.execute("SELECT count(*) FROM companies").fetchone()[0] == before
    finally:
        reset_settings_cache()
