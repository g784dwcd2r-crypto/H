from filings_hub.lake.storage import Storage
from filings_hub.research_index import ResearchIndex
from filings_hub.testing.preview_server import seed_pagination_index


def test_fresh_preview_pagination_is_complete_and_idempotent(tmp_path):
    storage = Storage(str(tmp_path / "lake"))
    index = ResearchIndex(path=tmp_path / "research.sqlite3")
    try:
        seed_pagination_index(index, storage)
        seed_pagination_index(index, storage)
        first = index.search("disclosurepaginationfixture", limit=20)
        second = index.search("disclosurepaginationfixture", limit=20, offset=20)
        assert first["total"] == second["total"] == 25
        assert len(first["results"]) == 20
        assert len(second["results"]) == 5
        assert first["next_offset"] == 20
        assert second["next_offset"] is None
        assert {row["document_id"] for row in first["results"]}.isdisjoint(
            {row["document_id"] for row in second["results"]}
        )
        assert all("Synthetic" in row["title"] for row in first["results"] + second["results"])
    finally:
        index.close()
