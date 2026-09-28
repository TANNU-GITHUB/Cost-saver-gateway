from app.config import Settings
from app.jev import JevClient


def test_jev_fallback_cache_validation():
    client = JevClient(Settings(mock_jev=True, jev_enabled=True))
    result = client.validate_cache(
        current_request="when is homework 1 due?",
        candidate_request="what is the deadline for hw1?",
        cached_answer="Homework 1 is due Friday.",
        similarity=0.89,
    )
    assert result.source in ("fallback", "heuristic")
    assert 0.0 <= result.confidence <= 1.0


def test_jev_fallback_routing():
    client = JevClient(Settings(mock_jev=True, jev_enabled=True))
    result = client.route_request(
        prompt="hello",
        estimated_tokens=5,
        has_code=False,
        reasoning_requested=False,
    )
    assert result.route in ("small", "large")
