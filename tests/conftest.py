import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app, state


@pytest.fixture(autouse=True)
def reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "true")
    monkeypatch.setenv("MOCK_JEV", "true")
    monkeypatch.setenv("REDIS_URL", "redis://invalid:1/0")
    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
