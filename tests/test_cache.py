from app.cache import cosine_similarity
from app.decision import is_volatile_prompt


def test_cosine_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) == 1.0


def test_volatile_prompt_detection():
    assert is_volatile_prompt("what happened in today's market?")
    assert not is_volatile_prompt("explain Python lists")
