from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class LLMProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        if self.settings.mock_llm or not self.settings.openai_api_key:
            return self._mock_response(model, messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.settings.openai_base_url.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()

    def _mock_response(self, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
        user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user = m.get("content", "")
                break
        content = (
            f"[mock-{model}] Processed your request ({len(user)} chars). "
            "Enable OPENAI_API_KEY and MOCK_LLM=false for live provider calls."
        )
        return {
            "id": f"chatcmpl-mock-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": estimate_tokens(user),
                "completion_tokens": estimate_tokens(content),
                "total_tokens": estimate_tokens(user) + estimate_tokens(content),
            },
        }

    async def stream_cached_content(self, content: str) -> AsyncIterator[bytes]:
        chunk_size = 24
        for i in range(0, len(content), chunk_size):
            part = content[i : i + chunk_size]
            payload = {
                "id": f"chatcmpl-cache-{int(time.time())}",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": part}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(payload)}\n\n".encode()
            await _async_sleep(0.01)
        done = {
            "id": f"chatcmpl-cache-{int(time.time())}",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(done)}\n\n".encode()
        yield b"data: [DONE]\n\n"


async def _async_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
