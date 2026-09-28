from app.config import Settings
from app.decision import heuristic_route
from app.jev import JevClient
from app.router import ModelRouter
from app.schemas import KeyPolicy


def test_heuristic_routes_simple_to_small():
    d = heuristic_route("What is 2+2?", estimated_tokens=10)
    assert d.route == "small"


def test_heuristic_routes_complex_to_large():
    d = heuristic_route("Prove step by step why this algorithm works", estimated_tokens=200)
    assert d.route == "large"


def test_policy_forces_large():
    settings = Settings(mock_jev=True, jev_enabled=True)
    router = ModelRouter(settings, JevClient(settings))
    d = router.decide("tiny", KeyPolicy(routing_mode="large"))
    assert d.route == "large"
    assert d.source == "policy"
