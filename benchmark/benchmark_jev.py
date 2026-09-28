#!/usr/bin/env python3
"""Offline evaluation of Jev fallback vs similarity-only cache policy."""

from __future__ import annotations

from app.config import Settings
from app.decision import borderline_cache_reuse_heuristic

PAIRS = [
    ("when is homework 1 due?", "what is the deadline for hw1?", 0.89, True),
    ("explain Python lists", "explain Python tuples", 0.88, False),
]


def main() -> None:
    settings = Settings(mock_jev=True)
    correct = 0
    for current, candidate, sim, expected in PAIRS:
        reuse, conf = borderline_cache_reuse_heuristic(current, candidate, sim)
        ok = reuse == expected
        correct += int(ok)
        print(
            f"sim={sim:.2f} expected={expected} got={reuse} conf={conf:.2f} ok={ok} | {current} / {candidate}"
        )
    print(f"accuracy={correct}/{len(PAIRS)}")


if __name__ == "__main__":
    main()
