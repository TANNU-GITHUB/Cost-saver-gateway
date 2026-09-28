from __future__ import annotations

import time
from contextlib import contextmanager

from prometheus_client import Counter, Gauge, Histogram

REQUESTS_TOTAL = Counter("gateway_requests_total", "Total gateway requests")
CACHE_HITS = Counter("gateway_cache_hits_total", "Cache hits")
CACHE_MISSES = Counter("gateway_cache_misses_total", "Cache misses")
FALSE_CACHE_HITS = Counter("gateway_false_cache_hits_total", "False cache hits (eval)")
JEV_CALLS = Counter("gateway_jev_calls_total", "Jev decision calls", ["kind"])
JEV_FALLBACKS = Counter("gateway_jev_fallbacks_total", "Jev fallbacks to deterministic policy")
JEV_CONFIDENCE = Histogram(
    "gateway_jev_confidence",
    "Jev confidence distribution",
    buckets=(0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.99, 1.0),
)
JEV_LATENCY = Histogram(
    "gateway_jev_latency_seconds",
    "Jev call latency",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)
ROUTING_SMALL = Counter("gateway_routing_small_total", "Small model routes")
ROUTING_LARGE = Counter("gateway_routing_large_total", "Large model routes")
ROUTING_FALLBACK = Counter("gateway_routing_fallback_total", "Routing fallbacks")
TOKENS_SAVED = Counter("gateway_tokens_saved_total", "Estimated tokens saved via cache")
COST_SAVED_USD = Counter("gateway_cost_saved_usd", "Estimated USD saved via cache")
LATENCY_CACHE = Histogram(
    "gateway_latency_cache_seconds",
    "Latency for cache hits",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5),
)
LATENCY_LLM = Histogram(
    "gateway_latency_llm_seconds",
    "Latency for LLM paths",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)
RATE_LIMIT_HITS = Counter("gateway_rate_limit_hits_total", "Rate limit rejections")
ACTIVE_REQUESTS = Gauge("gateway_active_requests", "In-flight requests")


@contextmanager
def track_request():
    ACTIVE_REQUESTS.inc()
    start = time.perf_counter()
    try:
        yield start
    finally:
        ACTIVE_REQUESTS.dec()


def record_jev(kind: str, confidence: float, latency_s: float, fallback: bool = False) -> None:
    JEV_CALLS.labels(kind=kind).inc()
    JEV_CONFIDENCE.observe(confidence)
    JEV_LATENCY.observe(latency_s)
    if fallback:
        JEV_FALLBACKS.inc()
