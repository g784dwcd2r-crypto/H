import httpx

from filings_hub import reader
from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage
from filings_hub.testing import edgar_fixtures as fx

BASE = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/"


def test_render_document_sanitises_rewrites_and_anchors():
    html = fx.document_html(fx.APPLE, fx.APPLE_FILINGS[0], fx.APPLE_FILINGS[0]["doc"])
    r = reader.render_document(html, BASE)
    out = r["html"]
    assert "<script" not in out and "onclick" not in out and "<iframe" not in out
    assert f'src="{BASE}chart.jpg"' in out  # relative image resolved to the filing folder
    assert 'href="#item7"' in out  # in-document anchors kept as they are
    titles = [t["title"] for t in r["toc"]]
    assert titles == [
        "PART I",
        "Item 1. Business",
        "Item 1A. Risk Factors",
        "Item 7. Management's Discussion and Analysis",
        "Item 8. Financial Statements",
        "CONSOLIDATED STATEMENTS OF OPERATIONS",
        "CONSOLIDATED BALANCE SHEETS",
    ]
    assert all(f'id="{t["id"]}"' in out for t in r["toc"])
    assert r["title"] == fx.APPLE_FILINGS[0]["doc"]


def test_render_document_keeps_content_of_unknown_tags_and_blocks_bad_urls():
    r = reader.render_document(
        '<p><ix:nonfraction name="us-gaap:Revenues">391,035</ix:nonfraction></p>'
        '<a href="javascript:alert(1)">x</a><img src="data:image/png;base64,AAAA">',
        BASE,
    )
    assert "391,035" in r["html"] and "ix:nonfraction" not in r["html"]
    assert "javascript:" not in r["html"] and "data:image" not in r["html"]


def test_html_to_text_and_search():
    text = reader.html_to_text("<p>One <b>two</b></p><style>p{}</style><div>Three&amp;four</div><script>x</script>")
    assert text == "One two\nThree&four"
    hits = reader.search_text("alpha buyback beta\ngamma BUYBACK delta", "buyback", context=6, max_hits=5)
    assert len(hits) == 2 and hits[0]["match"] == "buyback" and hits[1]["match"] == "BUYBACK"
    assert hits[0]["before"].endswith("alpha ") and hits[0]["after"].startswith(" beta")
    assert reader.search_text("x", "  ") == [] and len(reader.search_text("a a a a", "a", max_hits=2)) == 2


def test_reader_toc_preserves_existing_ids_and_avoids_generated_collisions():
    r = reader.render_document(
        '<span id="fh-0"></span><h2>Item 1. Business</h2>'
        '<h2 id="item7">Item 7. Management discussion</h2><a href="#item7">Original link</a>',
        BASE,
    )
    assert r["toc"][0]["id"] == "fh-0-section"
    assert r["toc"][1]["id"] == "item7"
    assert 'href="#item7"' in r["html"]
    assert all(r["html"].count(f'id="{entry["id"]}"') == 1 for entry in r["toc"])


def test_reader_duplicate_filer_ids_get_unique_toc_targets():
    r = reader.render_document('<div id="same"></div><h2 id="same">Item 7. Discussion</h2>', BASE)
    assert r["toc"][0]["id"] == "fh-0"
    assert '<span id="fh-0"></span><h2 id="same">' in r["html"]


def test_dropped_void_and_self_closing_tags_do_not_hide_following_content():
    html = "<input><embed/><p>Before</p><form><input><button>Hidden</button></form><script/><h2>Item 7. Discussion</h2>"
    r = reader.render_document(html, BASE)
    assert "Before" in r["html"] and r["toc"][0]["title"] == "Item 7. Discussion"
    assert "Hidden" not in r["html"] and "input" not in r["html"] and "embed" not in r["html"]
    assert reader.html_to_text(html) == "Before\nItem 7. Discussion"


def test_document_cache_memory_bound_and_lake_copy(tmp_path):
    st = Storage(str(tmp_path))
    c = EdgarClient("Test test@example.com", transport=httpx.MockTransport(fx.edgar_document_handler))
    cache = reader.DocumentCache(st, c, max_bytes=2000)
    f = fx.APPLE_FILINGS[0]
    raw = cache.fetch_document(fx.APPLE, f["acc"], f["doc"])
    assert b"PART I" in raw and st.exists(layout.raw_document(fx.APPLE, f["acc"], f["doc"]))
    text = cache.fetch_text(fx.APPLE, f["acc"], f["doc"])
    assert "buyback" in text and st.exists(layout.text_cache(fx.APPLE, f["acc"], f["doc"]))
    # over the memory budget the oldest entries go, but the lake copy still answers
    cache.fetch_document(fx.APPLE, fx.APPLE_FILINGS[1]["acc"], fx.APPLE_FILINGS[1]["doc"])
    assert cache._size <= 2000
    cache.client = None  # no network from here on
    assert cache.fetch_document(fx.APPLE, f["acc"], f["doc"]) == raw
