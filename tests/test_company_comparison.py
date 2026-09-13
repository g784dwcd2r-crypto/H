from filings_hub.platform import compare
from filings_hub.testing import edgar_fixtures as fx


def test_comparison_retains_period_unit_and_source(db):
    result = compare.compare_companies(db, [fx.APPLE, fx.JPM], "NetIncomeLoss", "FY2025", "IS")
    assert len(result["results"]) == 2
    for row in result["results"]:
        assert row["status"] == "available"
        assert row["value"] is not None and row["unit"] == "USD"
        assert row["period"]["period_end"] and row["evidence"]["sources"]
    missing = compare.compare_companies(db, [fx.APPLE], "MadeUpMetric", "FY2025", "IS")
    assert missing["results"][0]["status"] == "unavailable" and missing["results"][0]["value"] is None


def test_ambiguous_concept_does_not_silently_pick_a_line(monkeypatch, db):
    line = {"concept": "Cash", "is_abstract": False, "values": {"FY2025": 100}}
    monkeypatch.setattr(
        compare,
        "financial_snapshot",
        lambda *args, **kwargs: {
            "snapshot_id": "abc",
            "grid": {
                "company_name": "Example",
                "ticker": "EX",
                "periods": [{"period_label": "FY2025", "period_end": "2025-12-31"}],
                "statements": [{"code": "CF", "lines": [line, line]}],
            },
        },
    )
    result = compare.compare_companies(db, [1], "Cash", "FY2025", "CF")
    assert result["results"][0]["status"] == "ambiguous" and result["results"][0]["value"] is None
