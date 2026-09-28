from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    user: str | None = None


class KeyPolicy(BaseModel):
    cache_enabled: bool = True
    similarity_threshold: float | None = None
    jev_enabled: bool | None = None
    jev_confidence_threshold: float | None = None
    routing_mode: Literal["auto", "small", "large"] = "auto"
    rate_limit_per_hour: int | None = None


class CreateApiKeyRequest(BaseModel):
    name: str
    policy: KeyPolicy = Field(default_factory=KeyPolicy)


class CreateApiKeyResponse(BaseModel):
    api_key: str
    name: str
    policy: KeyPolicy


class CacheDecision(BaseModel):
    action: Literal["hit", "miss", "jev"]
    similarity: float | None = None
    candidate_prompt: str | None = None
    candidate_answer: str | None = None
    jev_reuse: bool | None = None
    jev_confidence: float | None = None
    jev_source: Literal["jev", "fallback", "skipped"] = "skipped"


class RouteDecision(BaseModel):
    route: Literal["small", "large", "fallback"]
    confidence: float
    source: Literal["jev", "heuristic", "policy", "fallback"]


class GatewayStats(BaseModel):
    total_requests: int
    cache_hits: int
    cache_misses: int
    cache_hit_rate: float
    jev_calls: int
    small_model_calls: int
    large_model_calls: int


class BenchmarkRow(BaseModel):
    config: str
    cache_hit_rate: float
    false_cache_hit_rate: float
    router_accuracy: float
    total_llm_cost: float
    jev_cost: float
    combined_cost: float
    p50_latency_ms: float
    p95_latency_ms: float
    llm_calls_avoided: int
    jev_fallback_rate: float


class BenchmarkReport(BaseModel):
    rows: list[BenchmarkRow]
    notes: str = ""


class HealthResponse(BaseModel):
    status: str
    redis: bool
    mock_llm: bool
    mock_jev: bool
    jev_enabled: bool


class AdminKeyRecord(BaseModel):
    name: str
    policy: KeyPolicy
    created_at: float


def extract_user_prompt(messages: list[ChatMessage]) -> str:
    user_parts = [m.content for m in messages if m.role == "user"]
    if not user_parts:
        return ""
    return user_parts[-1].strip()


def extract_system_prompt(messages: list[ChatMessage]) -> str:
    system_parts = [m.content for m in messages if m.role == "system"]
    return "\n".join(system_parts).strip()


def cache_namespace(
    *,
    system_prompt: str,
    project_id: str | None,
    model: str | None,
) -> str:
    parts = [system_prompt or "_", project_id or "_", model or "_"]
    return ":".join(parts)
