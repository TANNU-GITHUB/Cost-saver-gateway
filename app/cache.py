from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.config import Settings
from app.decision import is_volatile_prompt
from app.jev import JevClient
from app.schemas import CacheDecision, KeyPolicy

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    id: str
    prompt: str
    answer: str
    model: str
    embedding: list[float]
    metadata: dict[str, Any]
    created_at: float


class EmbeddingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None

    def embed(self, text: str) -> list[float]:
        if not text.strip():
            return [0.0] * 384
        try:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.settings.embedding_model)
            vec = self._model.encode(text, normalize_embeddings=True)
            return vec.tolist()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Embedding model unavailable, using hash fallback: %s", exc)
            return self._hash_embedding(text)

    @staticmethod
    def _hash_embedding(text: str, dim: int = 384) -> list[float]:
        rng = np.random.default_rng(abs(hash(text)) % (2**32))
        v = rng.standard_normal(dim)
        v = v / (np.linalg.norm(v) + 1e-9)
        return v.tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = (np.linalg.norm(va) * np.linalg.norm(vb)) + 1e-9
    return float(np.dot(va, vb) / denom)


class SemanticCache:
    def __init__(
        self,
        settings: Settings,
        redis_client: Any | None,
        embedder: EmbeddingService,
        jev: JevClient,
    ) -> None:
        self.settings = settings
        self.redis = redis_client
        self.embedder = embedder
        self.jev = jev
        self._memory: dict[str, list[CacheEntry]] = {}

    def _ns_key(self, namespace: str) -> str:
        return f"cache:ns:{namespace}"

    def _entry_key(self, namespace: str, entry_id: str) -> str:
        return f"cache:entry:{namespace}:{entry_id}"

    def store(
        self,
        *,
        namespace: str,
        prompt: str,
        answer: str,
        model: str,
        metadata: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        if is_volatile_prompt(prompt):
            return
        entry_id = str(uuid.uuid4())
        embedding = self.embedder.embed(prompt)
        entry = CacheEntry(
            id=entry_id,
            prompt=prompt,
            answer=answer,
            model=model,
            embedding=embedding,
            metadata=metadata or {},
            created_at=time.time(),
        )
        ttl = ttl_seconds or self.settings.cache_default_ttl_seconds
        if self.redis is None:
            self._memory.setdefault(namespace, []).append(entry)
            return
        payload = {
            "id": entry.id,
            "prompt": entry.prompt,
            "answer": entry.answer,
            "model": entry.model,
            "embedding": entry.embedding,
            "metadata": entry.metadata,
            "created_at": entry.created_at,
        }
        pipe = self.redis.pipeline()
        pipe.set(self._entry_key(namespace, entry_id), json.dumps(payload), ex=ttl)
        pipe.sadd(self._ns_key(namespace), entry_id)
        pipe.execute()

    def _load_entries(self, namespace: str) -> list[CacheEntry]:
        if self.redis is None:
            return list(self._memory.get(namespace, []))
        ids = self.redis.smembers(self._ns_key(namespace))
        entries: list[CacheEntry] = []
        for raw_id in ids:
            entry_id = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
            raw = self.redis.get(self._entry_key(namespace, entry_id))
            if not raw:
                continue
            payload = raw.decode() if isinstance(raw, bytes) else raw
            data = json.loads(payload)
            entries.append(
                CacheEntry(
                    id=data["id"],
                    prompt=data["prompt"],
                    answer=data["answer"],
                    model=data["model"],
                    embedding=data["embedding"],
                    metadata=data.get("metadata", {}),
                    created_at=data.get("created_at", 0),
                )
            )
        return entries

    def lookup(
        self,
        *,
        namespace: str,
        prompt: str,
        policy: KeyPolicy,
        high: float,
        low: float,
    ) -> CacheDecision:
        if not policy.cache_enabled or is_volatile_prompt(prompt):
            return CacheDecision(action="miss", jev_source="skipped")

        query_emb = self.embedder.embed(prompt)
        best: CacheEntry | None = None
        best_sim = -1.0
        for entry in self._load_entries(namespace):
            sim = cosine_similarity(query_emb, entry.embedding)
            if sim > best_sim:
                best_sim = sim
                best = entry

        if best is None:
            return CacheDecision(action="miss", similarity=None, jev_source="skipped")

        threshold_high = policy.similarity_threshold or high
        threshold_low = low

        if best_sim >= threshold_high:
            return CacheDecision(
                action="hit",
                similarity=best_sim,
                candidate_prompt=best.prompt,
                candidate_answer=best.answer,
                jev_source="skipped",
            )

        if best_sim <= threshold_low:
            return CacheDecision(action="miss", similarity=best_sim, jev_source="skipped")

        jev_result = self.jev.validate_cache(
            current_request=prompt,
            candidate_request=best.prompt,
            cached_answer=best.answer,
            similarity=best_sim,
        )
        conf_threshold = (
            policy.jev_confidence_threshold
            if policy.jev_confidence_threshold is not None
            else self.settings.jev_confidence_threshold
        )
        reuse = jev_result.reuse and jev_result.confidence >= conf_threshold
        return CacheDecision(
            action="hit" if reuse else "miss",
            similarity=best_sim,
            candidate_prompt=best.prompt,
            candidate_answer=best.answer,
            jev_reuse=reuse,
            jev_confidence=jev_result.confidence,
            jev_source="jev" if jev_result.source == "jev" else "fallback",
        )
