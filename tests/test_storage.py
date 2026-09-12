import pyarrow as pa

from filings_hub.lake.storage import Storage


def test_local_storage_roundtrip(tmp_path):
    st = Storage(str(tmp_path / "lake"))
    assert not st.is_remote and st.exists("") and st.ls("nope") == []
    st.write_text("a/b/c.txt", "hello")
    assert st.read_text("a/b/c.txt") == "hello" and st.size("a/b/c.txt") == 5
    assert st.ls("a") == ["a/b"] and st.glob("a/**/*.txt") == ["a/b/c.txt"]
    t = pa.table({"x": [1, 2]})
    st.write_parquet("p/q.parquet", t)
    assert st.read_parquet("p/q.parquet").equals(t)
    st.replace_dir_with_parquet("p", pa.table({"x": [3]}))
    assert st.ls("p") == ["p/part-0.parquet"]
    with st.open("a/b/c.txt", "rb") as f:
        assert f.read() == b"hello"
    with st.local_copy("a/b/c.txt") as p:
        assert p.read_text() == "hello"
    st.delete("a")
    assert not st.exists("a")
    st.delete("a")  # no-op
    assert st.duck_path("x") == st.full("x")
