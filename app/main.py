from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import redis
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.auth import ApiKeyStore, RateLimiter, require_admin, require_api_key
from app.cache import EmbeddingService, SemanticCache
from app.config import Settings, get_settings
from app.jev import JevClient
from app.metrics import (
    CACHE_HITS,
    CACHE_MISSES,
    COST_SAVED_USD,
    LATENCY_CACHE,
    LATENCY_LLM,
    REQUESTS_TOTAL,
    ROUTING_FALLBACK,
    ROUTING_LARGE,
    ROUTING_SMALL,
    TOKENS_SAVED,
    track_request,
)
from app.providers import LLMProvider
from app.router import ModelRouter
from app.schemas import (
    ChatCompletionRequest,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
    GatewayStats,
    HealthResponse,
    KeyPolicy,
    cache_namespace,
    extract_system_prompt,
    extract_user_prompt,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AppState:
    settings: Settings
    redis: Any
    key_store: ApiKeyStore
    rate_limiter: RateLimiter
    embedder: EmbeddingService
    jev: JevClient
    cache: SemanticCache
    router: ModelRouter
    provider: LLMProvider
    stats: dict[str, float]


state = AppState()


def get_redis(settings: Settings) -> Any | None:
    try:
        client = redis.from_url(settings.redis_url, decode_responses=False)
        client.ping()
        return client
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable, using in-memory fallbacks: %s", exc)
        return None


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    state.settings = settings
    state.redis = get_redis(settings)
    state.key_store = ApiKeyStore(settings, state.redis)
    state.rate_limiter = RateLimiter(settings, state.redis)
    state.embedder = EmbeddingService(settings)
    state.jev = JevClient(settings)
    state.cache = SemanticCache(settings, state.redis, state.embedder, state.jev)
    state.router = ModelRouter(settings, state.jev)
    state.provider = LLMProvider(settings)
    state.stats = {
        "total_requests": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "jev_calls": 0,
        "small_model_calls": 0,
        "large_model_calls": 0,
    }
    if state.key_store.get_record("gw_dev_default_key") is None:
        state.key_store._save(
            "gw_dev_default_key",
            {
                "name": "dev-default",
                "policy": KeyPolicy().model_dump(),
                "created_at": time.time(),
            },
        )
        logger.info("Default dev API key: gw_dev_default_key")
    yield


app = FastAPI(
    title="AI Cost-Saver Gateway",
    description="OpenAI-compatible gateway with semantic cache, Jev decisions, and routing",
    version="1.0.0",
    lifespan=lifespan,
)


def auth_context(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> tuple[str, Any]:
    api_key, policy = require_api_key(authorization, x_api_key, state.key_store, state.settings)
    limit = policy.rate_limit_per_hour or state.settings.default_rate_limit_per_hour
    state.rate_limiter.check(api_key, limit)
    return api_key, policy


@app.get("/")
async def root() -> HTMLResponse:
    html = """
    <!DOCTYPE html>
    <html><head><title>AI Cost-Saver Gateway</title>
    <style>body{font-family:system-ui;max-width:720px;margin:2rem auto;line-height:1.5}
    code{background:#f4f4f5;padding:.1rem .35rem;border-radius:4px}</style></head>
    <body>
    <h1>AI Cost-Saver Gateway</h1>
    <p>OpenAI-compatible gateway with semantic caching, Jev decisions, and model routing.</p>
    <ul>
      <li><a href="/docs">API docs</a></li>
      <li><a href="/health">Health</a></li>
      <li><a href="/metrics">Prometheus metrics</a></li>
    </ul>
    <p>Dev API key: <code>gw_dev_default_key</code></p>
    </body></html>
    """
    return HTMLResponse(html)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    redis_ok = False
    if state.redis is not None:
        try:
            state.redis.ping()
            redis_ok = True
        except Exception:  # noqa: BLE001
            redis_ok = False
    return HealthResponse(
        status="ok",
        redis=redis_ok,
        mock_llm=state.settings.mock_llm or not state.settings.openai_api_key,
        mock_jev=state.settings.mock_jev or not state.settings.typesafe_api_key,
        jev_enabled=state.settings.jev_enabled,
    )


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/v1/stats", response_model=GatewayStats)
async def gateway_stats(_: tuple[str, Any] = Depends(auth_context)) -> GatewayStats:
    total = int(state.stats["total_requests"])
    hits = int(state.stats["cache_hits"])
    misses = int(state.stats["cache_misses"])
    rate = (hits / total) if total else 0.0
    return GatewayStats(
        total_requests=total,
        cache_hits=hits,
        cache_misses=misses,
        cache_hit_rate=round(rate, 4),
        jev_calls=int(state.stats["jev_calls"]),
        small_model_calls=int(state.stats["small_model_calls"]),
        large_model_calls=int(state.stats["large_model_calls"]),
    )


@app.post("/admin/keys", response_model=CreateApiKeyResponse)
async def create_api_key(
    body: CreateApiKeyRequest,
    x_admin_secret: str | None = Header(default=None, alias="X-Admin-Secret"),
) -> CreateApiKeyResponse:
    require_admin(x_admin_secret, state.settings)
    return state.key_store.create_key(body)


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    body: ChatCompletionRequest,
    auth: tuple[str, Any] = Depends(auth_context),
) -> Response:
    _, policy = auth
    REQUESTS_TOTAL.inc()
    state.stats["total_requests"] += 1

    user_prompt = extract_user_prompt(body.messages)
    if not user_prompt:
        raise HTTPException(status_code=400, detail="User prompt is required")

    system_prompt = extract_system_prompt(body.messages)
    namespace = cache_namespace(
        system_prompt=system_prompt,
        project_id=request.headers.get("X-Project-Id"),
        model=body.model,
    )

    with track_request():
        start = time.perf_counter()
        decision = state.cache.lookup(
            namespace=namespace,
            prompt=user_prompt,
            policy=policy,
            high=state.settings.cache_similarity_high,
            low=state.settings.cache_similarity_low,
        )

        headers: dict[str, str] = {}
        if decision.jev_confidence is not None:
            state.stats["jev_calls"] += 1

        if decision.action == "hit" and decision.candidate_answer:
            CACHE_HITS.inc()
            state.stats["cache_hits"] += 1
            LATENCY_CACHE.observe(time.perf_counter() - start)
            saved_tokens = max(50, len(decision.candidate_answer) // 4)
            TOKENS_SAVED.inc(saved_tokens)
            COST_SAVED_USD.inc(saved_tokens * 0.000002)
            headers["X-Cache"] = "HIT"
            if decision.similarity is not None:
                headers["X-Cache-Similarity"] = f"{decision.similarity:.4f}"
            if decision.jev_confidence is not None:
                headers["X-Jev-Confidence"] = f"{decision.jev_confidence:.4f}"
                headers["X-Jev-Source"] = decision.jev_source

            content = decision.candidate_answer
            if body.stream:
                return StreamingResponse(
                    state.provider.stream_cached_content(content),
                    media_type="text/event-stream",
                    headers=headers,
                )

            payload = {
                "id": f"chatcmpl-cache-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": body.model or "cache",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": len(content) // 4, "total_tokens": len(content) // 4},
            }
            return JSONResponse(payload, headers=headers)

        CACHE_MISSES.inc()
        state.stats["cache_misses"] += 1
        headers["X-Cache"] = "MISS"
        if decision.similarity is not None:
            headers["X-Cache-Similarity"] = f"{decision.similarity:.4f}"

        route = state.router.decide(user_prompt, policy)
        model = body.model or state.router.model_name(route.route)
        headers["X-Model-Used"] = route.route
        headers["X-Route-Source"] = route.source
        headers["X-Route-Confidence"] = f"{route.confidence:.4f}"

        if route.route == "small":
            ROUTING_SMALL.inc()
            state.stats["small_model_calls"] += 1
        elif route.route == "large":
            ROUTING_LARGE.inc()
            state.stats["large_model_calls"] += 1
        else:
            ROUTING_FALLBACK.inc()

        messages = [m.model_dump() for m in body.messages]
        if body.stream:
            # Streaming from upstream not fully proxied in mock mode; stream final content.
            result = await state.provider.chat_completion(
                model=model,
                messages=messages,
                stream=False,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
            )
            content = result["choices"][0]["message"]["content"]
            LATENCY_LLM.observe(time.perf_counter() - start)
            state.cache.store(
                namespace=namespace,
                prompt=user_prompt,
                answer=content,
                model=model,
                metadata={"route": route.route},
            )
            return StreamingResponse(
                state.provider.stream_cached_content(content),
                media_type="text/event-stream",
                headers=headers,
            )

        result = await state.provider.chat_completion(
            model=model,
            messages=messages,
            stream=False,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
        LATENCY_LLM.observe(time.perf_counter() - start)
        content = result["choices"][0]["message"]["content"]
        state.cache.store(
            namespace=namespace,
            prompt=user_prompt,
            answer=content,
            model=model,
            metadata={"route": route.route},
        )
        return JSONResponse(result, headers=headers)


def create_app() -> FastAPI:
    return app
