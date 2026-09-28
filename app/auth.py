from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any

from fastapi import HTTPException, status

from app.config import Settings
from app.schemas import CreateApiKeyRequest, CreateApiKeyResponse, KeyPolicy


class ApiKeyStore:
    def __init__(self, settings: Settings, redis_client: Any | None) -> None:
        self.settings = settings
        self.redis = redis_client
        self._memory: dict[str, dict[str, Any]] = {}

    def _hash_key(self, api_key: str) -> str:
        return hashlib.sha256(api_key.encode()).hexdigest()

    def create_key(self, req: CreateApiKeyRequest) -> CreateApiKeyResponse:
        raw = f"gw_{secrets.token_urlsafe(24)}"
        record = {
            "name": req.name,
            "policy": req.policy.model_dump(),
            "created_at": time.time(),
        }
        self._save(raw, record)
        return CreateApiKeyResponse(api_key=raw, name=req.name, policy=req.policy)

    def _save(self, api_key: str, record: dict[str, Any]) -> None:
        h = self._hash_key(api_key)
        if self.redis is None:
            self._memory[h] = record
            return
        self.redis.set(f"apikey:{h}", json.dumps(record))

    def get_record(self, api_key: str) -> dict[str, Any] | None:
        h = self._hash_key(api_key)
        if self.redis is None:
            return self._memory.get(h)
        raw = self.redis.get(f"apikey:{h}")
        if not raw:
            return None
        payload = raw.decode() if isinstance(raw, bytes) else raw
        return json.loads(payload)

    def get_policy(self, api_key: str) -> KeyPolicy:
        record = self.get_record(api_key)
        if not record:
            return KeyPolicy()
        return KeyPolicy(**record["policy"])


class RateLimiter:
    def __init__(self, settings: Settings, redis_client: Any | None) -> None:
        self.settings = settings
        self.redis = redis_client
        self._memory: dict[str, list[float]] = {}

    def check(self, api_key: str, limit_per_hour: int) -> None:
        now = time.time()
        window_start = now - 3600
        key = self._hash(api_key)

        if self.redis is None:
            hits = [t for t in self._memory.get(key, []) if t >= window_start]
            if len(hits) >= limit_per_hour:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                )
            hits.append(now)
            self._memory[key] = hits
            return

        bucket = f"ratelimit:{key}"
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(bucket, 0, window_start)
        pipe.zadd(bucket, {str(now): now})
        pipe.zcard(bucket)
        pipe.expire(bucket, 3600)
        _, _, count, _ = pipe.execute()
        if count > limit_per_hour:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
            )

    @staticmethod
    def _hash(api_key: str) -> str:
        return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def require_api_key(
    authorization: str | None,
    x_api_key: str | None,
    store: ApiKeyStore,
    settings: Settings,
) -> tuple[str, KeyPolicy]:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif x_api_key:
        token = x_api_key.strip()

    if not token:
        raise HTTPException(status_code=401, detail="Missing API key")

    record = store.get_record(token)
    if record is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    policy = KeyPolicy(**record["policy"])
    return token, policy


def require_admin(admin_secret: str | None, settings: Settings) -> None:
    if admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Invalid admin secret")
