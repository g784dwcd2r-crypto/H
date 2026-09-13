"""Reproduce source-text fidelity checks in an isolated local lake. Never calls a model.

Expected literals come from the separately captured original-source manifest, not the extractor.
Download original URLs separately with permitted SEC access. This verifier reads local bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from filings_hub.lake.storage import Storage
from filings_hub.research_corpus import ResearchCorpus
from filings_hub.research_index import open_index
from filings_hub.research_ingest import extract


def validate(manifest_path: Path, raw_root: Path, lake_root: Path) -> dict:
    marker = lake_root / ".disclosure-research-validation"
    if lake_root.exists() and any(lake_root.iterdir()) and not marker.exists():
        raise ValueError("Refusing a non-empty lake without the isolated research-validation marker.")
    lake_root.mkdir(parents=True, exist_ok=True)
    marker.write_text("Isolated source validation; not a production corpus.\n")
    manifest = json.loads(manifest_path.read_text())
    storage = Storage(str(lake_root))
    index = open_index(storage, "")
    results = []
    try:
        for issuer in manifest["issuers"]:
            for source in issuer["sources"]:
                row = {
                    "cik": issuer["cik"],
                    "issuer": issuer["name"],
                    "accession": source["accession"],
                    "form": source["form"],
                    "source_url": source["source_url"],
                    "sha256": source["sha256"],
                }
                name = source["raw_filename"]
                if Path(name).name != name:
                    raise ValueError("Raw manifest paths must be filenames within the selected raw directory.")
                try:
                    raw = (raw_root / name).read_bytes()
                    if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                        raise ValueError("Original source hash does not match the frozen expectation.")
                    filing = {
                        "cik": issuer["cik"],
                        "accession": source["accession"],
                        "form": source["form"],
                        "filed_date": source["filed_date"],
                        "company_name": issuer["name"],
                    }
                    doc = index.register_document(filing, {"filename": source["filename"]})
                    text, pages = extract(raw, source["filename"])
                    version = index.add_version(storage, doc, raw, text, pages)
                    plain = " ".join(text.split())
                    expected, numeric = source["expected_period_literal"], source["numeric_literal_candidate"]
                    row.update(
                        status="indexed",
                        document_id=doc,
                        version_id=version,
                        characters=len(text),
                        period_literal_preserved=None if not expected else " ".join(expected["text"].split()) in plain,
                        numeric_literal_preserved=None if not numeric else numeric["text"].strip() in plain,
                    )
                except (OSError, ValueError) as error:
                    row.update(status="excluded", reason=str(error))
                results.append(row)
        corpus = ResearchCorpus(index)
        while corpus.prepare(limit=10)["prepared_versions"]:
            pass
        primary = [r for r in results if r.get("period_literal_preserved") is not None]
        report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "manifest": manifest_path.name,
            "scope": "Original source text fidelity only; not model accuracy or normalized financial-data validation.",
            "issuer_count": len(manifest["issuers"]),
            "documents": len(results),
            "indexed": sum(r["status"] == "indexed" for r in results),
            "exclusions": [r for r in results if r["status"] != "indexed"],
            "period_expectations": len(primary),
            "period_literals_preserved": sum(r["period_literal_preserved"] for r in primary),
            "numeric_candidate_checks": sum(r.get("numeric_literal_preserved") is not None for r in results),
            "numeric_candidate_literals_preserved": sum(r.get("numeric_literal_preserved") is True for r in results),
            "corpus": corpus.health(),
            "results": results,
        }
        (lake_root / "source-validation-results.json").write_text(json.dumps(report, indent=2) + "\n")
        return report
    finally:
        index.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("docs/validation/research-32-issuers.json"))
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--lake", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.manifest, args.raw_root, args.lake)
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, indent=2))
    raise SystemExit(
        0 if not result["exclusions"] and result["period_literals_preserved"] == result["issuer_count"] else 1
    )


if __name__ == "__main__":
    main()
