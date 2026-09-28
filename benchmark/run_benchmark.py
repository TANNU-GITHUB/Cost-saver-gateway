#!/usr/bin/env python3
"""Run gateway benchmark comparing baseline, cache-only, and Jev-enabled paths."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass

import httpx

SAMPLES = [
    ("dup", "when is homework 1 due?"),
    ("dup", "what is the deadline for hw1?"),
    ("diff", "explain Python lists"),
    ("diff", "explain Python tuples"),
    ("simple", "what is 2+2?"),
    ("complex", "derive the time complexity of merge sort step by step"),
    ("volatile", "what happened in today's market?"),
]


@dataclass
class RunStats:
    latencies_ms: list[float]
    cache_hits: int
    cache_misses: int
    small: int
    large: int


def run_config(base_url: str, api_key: str, repeats: int) -> RunStats:
    latencies: list[float] = []
    hits = misses = small = large = 0
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        for _ in range(repeats):
            for _, prompt in SAMPLES:
                start = time.perf_counter()
                resp = client.post(
                    "/v1/chat/completions",
                    headers=headers,
                    json={"messages": [{"role": "user", "content": prompt}]},
                )
                resp.raise_for_status()
                latencies.append((time.perf_counter() - start) * 1000)
                cache = resp.headers.get("X-Cache", "MISS")
                if cache == "HIT":
                    hits += 1
                else:
                    misses += 1
                route = resp.headers.get("X-Model-Used", "")
                if route == "small":
                    small += 1
                elif route == "large":
                    large += 1
    return RunStats(latencies, hits, misses, small, large)


def pctl(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = int((len(values) - 1) * p)
    return values[idx]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8801")
    parser.add_argument("--api-key", default="gw_dev_default_key")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    stats = run_config(args.base_url, args.api_key, args.repeats)
    total = stats.cache_hits + stats.cache_misses
    report = {
        "config": "gateway-with-jev",
        "requests": total,
        "cache_hit_rate": round(stats.cache_hits / total, 4) if total else 0,
        "p50_latency_ms": round(pctl(stats.latencies_ms, 0.5), 2),
        "p95_latency_ms": round(pctl(stats.latencies_ms, 0.95), 2),
        "small_model_calls": stats.small,
        "large_model_calls": stats.large,
        "mean_latency_ms": round(statistics.mean(stats.latencies_ms), 2) if stats.latencies_ms else 0,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
