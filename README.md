# AI Cost-Saver Gateway (with Jev)

Production-shaped OpenAI-compatible gateway that reduces LLM cost and latency using:

- Semantic caching (Redis + `all-MiniLM-L6-v2`)
- Three-zone cache policy (high / low / borderline → Jev)
- Jev (TypeSafe System One) for cache validation and model routing
- Confidence-aware fallbacks when Jev or Redis is unavailable
- Prometheus metrics and Grafana dashboards
- Per-API-key policies and rate limits

## Architecture

```text
Client → FastAPI Gateway → Auth/Rate limit → Embeddings → Semantic search
  → (high hit | low miss | borderline → Jev) → Small/Large LLM → cache store → metrics
```

Jev does **not** generate answers. It returns structured decisions (reuse cache, route model, confidence).

## Quick start

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8801
```

Default dev API key: `gw_dev_default_key`

### Docker Compose (gateway + Redis + Prometheus + Grafana)

```bash
docker compose up --build
```

- Gateway: http://localhost:8801
- Grafana: http://localhost:3000 (admin / admin)
- Prometheus: http://localhost:9090

## API

### Chat completions

`POST /v1/chat/completions` (OpenAI-compatible)

Headers:

- `Authorization: Bearer <api_key>`
- `X-Project-Id` (optional cache namespace)

Response headers:

- `X-Cache: HIT|MISS`
- `X-Model-Used: small|large`
- `X-Route-Source: jev|heuristic|policy|fallback`
- `X-Route-Confidence: 0.94`
- `X-Jev-Confidence` (borderline cache decisions)

### Admin API keys

```bash
curl -X POST http://localhost:8801/admin/keys \
  -H "X-Admin-Secret: change-me-admin-secret" \
  -H "Content-Type: application/json" \
  -d '{"name":"team-a","policy":{"cache_enabled":true,"jev_enabled":true,"routing_mode":"auto"}}'
```

Per-key policy fields:

- `cache_enabled`
- `similarity_threshold`
- `jev_enabled`
- `jev_confidence_threshold`
- `routing_mode` (`auto`, `small`, `large`)
- `rate_limit_per_hour`

## Configuration

See `.env.example`.

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Upstream LLM provider |
| `MOCK_LLM` | Local mock responses when true |
| `TYPESAFE_API_KEY` | Live Jev / TypeSafe API |
| `MOCK_JEV` | Deterministic Jev fallback when true |
| `CACHE_SIMILARITY_HIGH` / `LOW` | Three-zone thresholds |
| `REDIS_URL` | Semantic cache backend |

## Cache safety

- Namespace includes system prompt, project ID, and model
- TTL on cache entries
- Volatile prompts (`today`, `now`, `latest`, …) skip cache
- Borderline similarity routed to Jev with confidence threshold

## Benchmarks

```bash
python benchmark/benchmark_jev.py
python benchmark/run_benchmark.py --base-url http://127.0.0.1:8801
```

`run_benchmark.py` exercises duplicates, paraphrases, similar-but-different prompts, simple/complex, and volatile queries.

## Tests

```bash
pytest -q
```

## Demo flow

1. First request → `X-Cache: MISS`, routed small/large, answer stored
2. Rephrased question (borderline) → Jev validates → `X-Cache: HIT`
3. Similar but different intent → Jev rejects reuse → LLM called
4. Complex prompt → Jev routes to large model

Open Grafana to inspect cache hit rate, cost saved, latency, Jev confidence, and fallback rate.

## Resume bullets (fill with your measured benchmark)

- Built an OpenAI-compatible AI gateway using semantic caching, Jev-based decisioning, and confidence-aware model routing; reduced redundant LLM calls by **X%** and lowered p95 latency by **Y%** across a 1,000-request benchmark.
- Designed a confidence-aware cache validation layer using Jev to distinguish true semantic duplicates from similar-but-different requests, achieving a false-cache-hit rate of **Z%**.
