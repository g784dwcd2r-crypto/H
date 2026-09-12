# Notebooks

Exploration only; nothing here is part of the pipeline. A useful starting point:

```python
from filings_hub.lake.storage import Storage
from filings_hub.lake.duck import Duck

duck = Duck(Storage("./data"))
duck.create_views()
duck.fetch_arrow("SELECT * FROM periods WHERE cik = 320193 ORDER BY period_end DESC").to_pandas()
duck.fetch_arrow("""
  SELECT line_order, label, value_presented FROM statements
  WHERE accession = '0000320193-25-000079' AND statement = 'IS' AND is_primary_period ORDER BY line_order
""").to_pandas()
```
