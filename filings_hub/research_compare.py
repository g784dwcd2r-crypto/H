"""Deterministic, bounded differences between immutable extracted source texts.

Access checks belong to ResearchIndex before this pure comparison function is called.
No inferred accounting, semantic change labels or AI interpretation is produced.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

MAX_INPUT_CHARACTERS = 100_000
MAX_INPUT_LINES = 2000
MAX_OUTPUT_CHARACTERS = 100_000
VERSION_FIELDS = (
    "version_id",
    "content_sha256",
    "indexed_at",
    "extractor_version",
    "content_bytes",
    "title",
    "filename",
    "source_url",
    "cik",
    "accession",
    "form",
    "filed_date",
)


def version_metadata(version: dict[str, Any]) -> dict[str, Any]:
    return {key: version.get(key) for key in VERSION_FIELDS}


def _bounded_lines(text: str) -> tuple[list[str], int]:
    lines = text[:MAX_INPUT_CHARACTERS].splitlines(keepends=True)[:MAX_INPUT_LINES]
    return lines, sum(len(line) for line in lines)


def compare_texts(
    before: dict[str, Any], after: dict[str, Any], *, context: int = 3, max_hunks: int = 20, max_lines: int = 600
) -> dict[str, Any]:
    if not 0 <= context <= 10 or not 1 <= max_hunks <= 50 or not 1 <= max_lines <= 1000:
        raise ValueError("context must be 0–10, max_hunks 1–50, and max_lines 1–1,000")
    if before["document_id"] != after["document_id"]:
        raise ValueError("Only two versions of the same indexed document can be compared.")
    left_text, right_text = before["text_content"], after["text_content"]
    identical = left_text == right_text
    left, left_count = _bounded_lines(left_text)
    right, right_count = _bounded_lines(right_text)
    groups = [] if identical else list(SequenceMatcher(None, left, right, autojunk=False).get_grouped_opcodes(context))
    input_truncated = not identical and (left_count < len(left_text) or right_count < len(right_text))
    result: dict[str, Any] = {
        "comparison": "extracted-text-v1",
        "document_id": before["document_id"],
        "before": version_metadata(before),
        "after": version_metadata(after),
        "text_identical": identical,
        "complete": False,
        "input_truncated": input_truncated,
        "output_truncated": len(groups) > max_hunks,
        "total_hunks_in_compared_text": len(groups),
        "hunks": [],
        "coverage": {
            "before_characters_total": len(left_text),
            "after_characters_total": len(right_text),
            "before_characters_compared": len(left_text) if identical else left_count,
            "after_characters_compared": len(right_text) if identical else right_count,
        },
        "limits": {
            "context": context,
            "max_hunks": max_hunks,
            "max_lines": max_lines,
            "input_characters_per_version": MAX_INPUT_CHARACTERS,
            "input_lines_per_version": MAX_INPUT_LINES,
            "output_characters": MAX_OUTPUT_CHARACTERS,
        },
        "limitations": [
            "Differences concern stored extracted text, not PDF/HTML appearance or accounting interpretation.",
            "Whitespace is significant; unchanged extracted text does not prove identical source bytes.",
            "Hunk totals cover only compared text; incomplete results are not a complete change list.",
        ],
    }
    lines_used = characters_used = 0
    stop = False
    for group in groups[:max_hunks]:
        first, last = group[0], group[-1]
        hunk = {
            "before_start": first[1] + 1 if last[2] > first[1] else first[1],
            "before_count": last[2] - first[1],
            "after_start": first[3] + 1 if last[4] > first[3] else first[3],
            "after_count": last[4] - first[3],
            "lines": [],
            "truncated": False,
        }
        result["hunks"].append(hunk)
        for tag, i1, i2, j1, j2 in group:
            rows = []
            if tag == "equal":
                rows = [
                    {"kind": "context", "before_line": i + 1, "after_line": j + 1, "text": left[i]}
                    for i, j in zip(range(i1, i2), range(j1, j2), strict=True)
                ]
            else:
                if tag in ("delete", "replace"):
                    rows += [
                        {"kind": "delete", "before_line": i + 1, "after_line": None, "text": left[i]}
                        for i in range(i1, i2)
                    ]
                if tag in ("insert", "replace"):
                    rows += [
                        {"kind": "insert", "before_line": None, "after_line": j + 1, "text": right[j]}
                        for j in range(j1, j2)
                    ]
            for row in rows:
                if lines_used >= max_lines or characters_used + len(row["text"]) > MAX_OUTPUT_CHARACTERS:
                    result["output_truncated"] = hunk["truncated"] = stop = True
                    break
                hunk["lines"].append(row)
                lines_used += 1
                characters_used += len(row["text"])
            if stop:
                break
        if stop:
            break
    result["complete"] = not result["input_truncated"] and not result["output_truncated"]
    return result
