"""Synthetic provider for deterministic tests only. Never selected by runtime configuration."""

from filings_hub.research_provider import OpenAIResearchProvider


class FixtureResearchProvider(OpenAIResearchProvider):
    name = "fixture"
    fixture = True

    def __init__(self):
        super().__init__("fixture-only", "synthetic-research-fixture", "synthetic-embedding-fixture")
        self.calls = []
        self.reject = False
        self.bad_quote = False

    def embed(self, texts):
        self.calls.append(("embed", texts))
        vectors = [[1.0, float("liquidity" in text.lower()), float("revenue" in text.lower())] for text in texts]
        return vectors, {"provider_calls": 1, "input_tokens": 10, "output_tokens": 0}

    def structured(self, instructions, payload, schema, *, name, max_tokens):
        self.calls.append((name, payload))
        if name == "research_relevance":
            data = {"ordered_span_ids": [p["span_id"] for p in payload["passages"]][: self.retrieved_passage_limit]}
        elif name == "cited_research":
            passage = payload["passages"][0]
            unsupported = "unsupported" in payload["question"].lower()
            data = {
                "claims": []
                if unsupported
                else [
                    {
                        "id": "claim-1",
                        "text": "The selected filing states: " + passage["text"][:700],
                        "evidence": [
                            {
                                "span_id": passage["span_id"],
                                "relationship": "supporting",
                                "quote": "invented quotation" if self.bad_quote else passage["text"][:700],
                            }
                        ],
                    }
                ],
                "insufficient": unsupported,
                "limitations": [],
            }
        else:
            contradictions = [p["span_id"] for p in payload["passages"] if "contradictory" in p["text"].lower()]
            data = {
                "assessments": [
                    {
                        "id": c["id"],
                        "supported": not self.reject,
                        "reason": "Synthetic fixture verdict.",
                        "contradictory_span_ids": contradictions,
                    }
                    for c in payload["claims"]
                ]
            }
        return data, {"provider_calls": 1, "input_tokens": 20, "output_tokens": 20}
