from __future__ import annotations

import re

from app.schemas import RouteDecision

VOLATILE_PATTERN = re.compile(
    r"\b(today|now|latest|current|live|real-?time|this week|right now)\b",
    re.IGNORECASE,
)

CODE_PATTERN = re.compile(r"```|\bdef\b|\bclass\b|\bfunction\b|\bimport\b", re.IGNORECASE)
REASONING_PATTERN = re.compile(
    r"\b(reason|prove|step by step|analyze|derive|why does)\b",
    re.IGNORECASE,
)


def is_volatile_prompt(text: str) -> bool:
    return bool(VOLATILE_PATTERN.search(text))


def heuristic_route(prompt: str, *, estimated_tokens: int) -> RouteDecision:
    if CODE_PATTERN.search(prompt) or REASONING_PATTERN.search(prompt):
        return RouteDecision(route="large", confidence=0.75, source="heuristic")
    if estimated_tokens > 120 or len(prompt) > 400:
        return RouteDecision(route="large", confidence=0.7, source="heuristic")
    return RouteDecision(route="small", confidence=0.72, source="heuristic")


def apply_route_confidence_policy(
    jev_route: RouteDecision,
    *,
    high_threshold: float = 0.9,
    medium_threshold: float = 0.75,
) -> RouteDecision:
    if jev_route.confidence >= high_threshold:
        return jev_route
    if jev_route.confidence >= medium_threshold:
        fallback = heuristic_route("", estimated_tokens=0)
        return RouteDecision(
            route=fallback.route,
            confidence=fallback.confidence,
            source="fallback",
        )
    return RouteDecision(route="large", confidence=0.6, source="fallback")


def borderline_cache_reuse_heuristic(
    current: str,
    candidate: str,
    similarity: float,
) -> tuple[bool, float]:
    """Deterministic fallback when Jev is unavailable."""
    cur = current.lower().strip()
    cand = candidate.lower().strip()
    if cur == cand:
        return True, 0.99
    if similarity >= 0.92:
        return True, min(0.95, similarity)
    if similarity <= 0.82:
        return False, max(0.5, 1.0 - similarity)
    # Similar wording but different entities (hw1 vs lists/tuples heuristic)
    tokens_cur = set(re.findall(r"\w+", cur))
    tokens_cand = set(re.findall(r"\w+", cand))
    overlap = len(tokens_cur & tokens_cand) / max(len(tokens_cur | tokens_cand), 1)
    reuse = overlap >= 0.55 and similarity >= 0.86
    return reuse, 0.65 + overlap * 0.3
