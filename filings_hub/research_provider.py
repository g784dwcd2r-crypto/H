"""Bounded, server-only OpenAI adapter. No tools, automatic retries, or hosted file stores.

Structured output controls shape; it does not establish that a cited claim is true.
The caller checks source quotes and uses a separate support-assessment call before disclosure.
"""

from __future__ import annotations

import json
import math
import threading
from typing import Any

import httpx


class ProviderUnavailable(RuntimeError):
    def __init__(self, message: str, *, attempted_calls=0):
        super().__init__(message)
        self.attempted_calls = attempted_calls


class OpenAIResearchProvider:
    name = "openai"
    fixture = False
    base_url = "https://api.openai.com/v1/"

    def __init__(
        self,
        key: str,
        model: str,
        embedding_model: str,
        *,
        client=None,
        readiness="ready",
        retrieval_mode="hybrid",
        max_requests=None,
        input_character_limit=100_000,
        output_token_limit=1800,
        rerank_candidate_limit=24,
        retrieved_passage_limit=12,
    ):
        self.key, self.model, self.embedding_model = key, model, embedding_model
        self.client = client
        self.readiness = readiness
        self.retrieval_mode = retrieval_mode
        self.max_requests = max_requests
        self.request_count = 0
        self.request_lock = threading.Lock()
        self.input_character_limit = input_character_limit
        self.output_token_limit = output_token_limit
        if not 1 <= retrieved_passage_limit <= rerank_candidate_limit <= 24:
            raise ValueError("Reranking bounds require 1–24 candidates and no more retrieved passages than candidates.")
        self.rerank_candidate_limit = rerank_candidate_limit
        self.retrieved_passage_limit = retrieved_passage_limit

    @property
    def configured(self):
        return bool(self.key and self.model and (self.embedding_model or self.retrieval_mode == "lexical_rerank"))

    @property
    def embedding_key(self):
        return self.name + ":" + self.embedding_model

    def status(self):
        return {
            "configured": self.configured,
            "provider": self.name if self.key else "disabled",
            "model": self.model or None,
            "fixture": self.fixture,
            "readiness": self.readiness if self.key else "not_configured",
            "available": self.configured and self.readiness == "ready",
            "retrieval_mode": self.retrieval_mode,
        }

    def request(self, endpoint: str, payload: dict, *, timeout: int):
        if not self.configured or self.readiness != "ready":
            raise ProviderUnavailable("Research requires an enabled provider, server API key and model configuration.")
        serialized = json.dumps(payload, ensure_ascii=False)
        encoded = serialized.encode()
        if len(encoded) > 100_000 or len(serialized) > self.input_character_limit:
            raise ProviderUnavailable("Provider input exceeds its configured per-call bound.")
        with self.request_lock:
            if self.max_requests is not None and self.request_count >= self.max_requests:
                raise ProviderUnavailable("Explicit live acceptance call allowance reached.")
            self.request_count += 1
        try:
            with (
                httpx.Client(timeout=timeout) if self.client is None else _borrow(self.client) as client,
                client.stream(
                    "POST",
                    self.base_url + endpoint,
                    headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"},
                    content=encoded,
                ) as response,
            ):
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 1_000_000:
                        raise ProviderUnavailable(
                            "Provider response exceeds the response-size bound.", attempted_calls=1
                        )
                    chunks.append(chunk)
                return json.loads(b"".join(chunks))
        except (httpx.HTTPError, ValueError) as exc:
            # No provider body, key, prompt, or document text reaches logs/errors.
            raise ProviderUnavailable(
                "Research provider request failed; no automatic billed retry was made.", attempted_calls=1
            ) from exc

    def embed(self, texts: list[str]) -> tuple[list[list[float]], dict]:
        if not 1 <= len(texts) <= 32 or sum(len(t.encode()) for t in texts) > 64_000:
            raise ProviderUnavailable("Embedding batch exceeds 32 inputs or 64 KB.")
        data = self.request(
            "embeddings", {"model": self.embedding_model, "input": texts, "encoding_format": "float"}, timeout=20
        )
        items = sorted(data.get("data", []), key=lambda r: r.get("index", -1))
        if [r.get("index") for r in items] != list(range(len(texts))):
            raise ProviderUnavailable("Provider returned an incomplete embedding batch.", attempted_calls=1)
        vectors = [r.get("embedding", []) for r in items]
        if (
            not vectors
            or not 1 <= len(vectors[0]) <= 8192
            or any(
                len(v) != len(vectors[0])
                or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in v)
                or not any(v)
                for v in vectors
            )
        ):
            raise ProviderUnavailable("Provider returned invalid embedding vectors.", attempted_calls=1)
        usage = data.get("usage", {})
        return vectors, {
            "input_tokens": int(usage.get("prompt_tokens", usage.get("total_tokens", 0))),
            "output_tokens": 0,
            "provider_calls": 1,
        }

    def structured(self, instructions: str, payload: dict, schema: dict, *, name: str, max_tokens: int):
        data = self.request(
            "responses",
            {
                "model": self.model,
                "instructions": instructions,
                "input": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                "store": False,
                "max_output_tokens": min(max_tokens, self.output_token_limit),
                "truncation": "disabled",
                "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
            },
            timeout=60,
        )
        if data.get("status") != "completed":
            raise ProviderUnavailable("Provider did not complete its bounded response.", attempted_calls=1)
        parts = [
            part.get("text", "")
            for item in data.get("output", [])
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        ]
        try:
            result = json.loads("".join(parts))
        except (ValueError, TypeError) as exc:
            raise ProviderUnavailable("Provider returned no usable structured answer.", attempted_calls=1) from exc
        usage = data.get("usage", {})
        return result, {
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "provider_calls": 1,
        }


class _borrow:
    def __init__(self, value: Any):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *args):
        return False


class XAIResearchProvider(OpenAIResearchProvider):
    """xAI's documented Responses/embedding shapes, with separately configured model entitlements."""

    name = "xai"
    base_url = "https://api.x.ai/v1/"


def provider_from_settings(settings):
    if settings.research_provider == "xai":
        return XAIResearchProvider(
            settings.xai_api_key if settings.research_enabled else "",
            settings.research_xai_model,
            settings.research_xai_embedding_model,
            readiness=settings.research_provider_readiness,
            retrieval_mode=settings.research_retrieval_mode,
        )
    return OpenAIResearchProvider(
        settings.research_openai_api_key if settings.research_enabled else "",
        settings.research_answer_model,
        settings.research_embedding_model,
        readiness=settings.research_provider_readiness,
        retrieval_mode=settings.research_retrieval_mode,
    )
