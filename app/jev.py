from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.config import Settings
from app.decision import borderline_cache_reuse_heuristic, is_volatile_prompt
from app.metrics import record_jev
from app.schemas import RouteDecision

logger = logging.getLogger(__name__)


@dataclass
class CacheValidationResult:
    reuse: bool
    confidence: float
    volatile: bool
    source: str


@dataclass
class RoutingResult:
    route: str
    confidence: float
    source: str


class JevClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        if self.settings.mock_jev or not self.settings.typesafe_api_key:
            return None
        try:
            from typesafe_sdk import TypeSafeClient

            self._client = TypeSafeClient(
                api_key=self.settings.typesafe_api_key,
                base_url=self.settings.typesafe_base_url,
                model=self.settings.jev_model,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to init TypeSafe client: %s", exc)
            self._client = None
        return self._client

    def validate_cache(
        self,
        *,
        current_request: str,
        candidate_request: str,
        cached_answer: str,
        similarity: float,
    ) -> CacheValidationResult:
        start = time.perf_counter()
        volatile = is_volatile_prompt(current_request)
        if volatile:
            result = CacheValidationResult(
                reuse=False,
                confidence=0.95,
                volatile=True,
                source="heuristic",
            )
            record_jev("cache_validation", result.confidence, time.perf_counter() - start)
            return result

        client = self._get_client()
        if client is None or not self.settings.jev_enabled:
            reuse, conf = borderline_cache_reuse_heuristic(
                current_request, candidate_request, similarity
            )
            result = CacheValidationResult(
                reuse=reuse,
                confidence=conf,
                volatile=False,
                source="fallback",
            )
            record_jev(
                "cache_validation",
                result.confidence,
                time.perf_counter() - start,
                fallback=True,
            )
            return result

        try:
            from typesafe_sdk import Noul

            state = (
                f"Current user request:\n{current_request}\n\n"
                f"Candidate cached request:\n{candidate_request}\n\n"
                f"Cached answer:\n{cached_answer[:1500]}\n\n"
                f"Similarity score:\n{similarity:.4f}"
            )
            with client:
                response = client.system_one(
                    state=state,
                    questions={
                        "safe_reuse": Noul(
                            instructions=(
                                "Does the cached answer safely satisfy the current "
                                "user request (same intent)?"
                            ),
                        ),
                        "volatile": Noul(
                            instructions=(
                                "Is the current request volatile or time-sensitive "
                                "(e.g. today, now, latest news)?"
                            ),
                        ),
                    },
                )
            reuse = bool(response.answers["safe_reuse"].noul >= 0.5)
            conf = float(response.answers["safe_reuse"].noul)
            volatile_jev = bool(response.answers["volatile"].noul >= 0.5)
            if volatile_jev:
                reuse = False
            result = CacheValidationResult(
                reuse=reuse,
                confidence=conf,
                volatile=volatile_jev,
                source="jev",
            )
            record_jev("cache_validation", conf, time.perf_counter() - start)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("Jev cache validation failed: %s", exc)
            reuse, conf = borderline_cache_reuse_heuristic(
                current_request, candidate_request, similarity
            )
            result = CacheValidationResult(
                reuse=reuse,
                confidence=conf,
                volatile=False,
                source="fallback",
            )
            record_jev(
                "cache_validation",
                conf,
                time.perf_counter() - start,
                fallback=True,
            )
            return result

    def route_request(
        self,
        *,
        prompt: str,
        estimated_tokens: int,
        has_code: bool,
        reasoning_requested: bool,
    ) -> RoutingResult:
        start = time.perf_counter()
        client = self._get_client()
        if client is None or not self.settings.jev_enabled:
            from app.decision import heuristic_route

            h = heuristic_route(prompt, estimated_tokens=estimated_tokens)
            record_jev(
                "routing",
                h.confidence,
                time.perf_counter() - start,
                fallback=True,
            )
            return RoutingResult(route=h.route, confidence=h.confidence, source=h.source)

        try:
            from typesafe_sdk import Choice

            state = (
                f"Prompt:\n{prompt}\n\n"
                f"Estimated tokens: {estimated_tokens}\n"
                f"Contains code: {has_code}\n"
                f"Reasoning requested: {reasoning_requested}"
            )
            with client:
                response = client.system_one(
                    state=state,
                    questions={
                        "route": Choice(
                            instructions="Which model tier should handle this request?",
                            criteria={
                                "small": "Simple FAQ, short answers, low complexity",
                                "large": "Complex reasoning, code, multi-step tasks",
                            },
                        ),
                    },
                )
            route = response.answers["route"].choice
            conf = float(response.answers["route"].confidence)
            if route not in ("small", "large"):
                route = "large"
            result = RoutingResult(route=route, confidence=conf, source="jev")
            record_jev("routing", conf, time.perf_counter() - start)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("Jev routing failed: %s", exc)
            from app.decision import heuristic_route

            h = heuristic_route(prompt, estimated_tokens=estimated_tokens)
            record_jev(
                "routing",
                h.confidence,
                time.perf_counter() - start,
                fallback=True,
            )
            return RoutingResult(route=h.route, confidence=h.confidence, source="fallback")
