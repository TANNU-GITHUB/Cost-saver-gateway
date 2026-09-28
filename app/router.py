from __future__ import annotations

from app.config import Settings
from app.decision import CODE_PATTERN, REASONING_PATTERN, apply_route_confidence_policy
from app.jev import JevClient
from app.providers import estimate_tokens
from app.schemas import KeyPolicy, RouteDecision


class ModelRouter:
    def __init__(self, settings: Settings, jev: JevClient) -> None:
        self.settings = settings
        self.jev = jev

    def decide(self, prompt: str, policy: KeyPolicy) -> RouteDecision:
        if policy.routing_mode == "small":
            return RouteDecision(route="small", confidence=1.0, source="policy")
        if policy.routing_mode == "large":
            return RouteDecision(route="large", confidence=1.0, source="policy")

        tokens = estimate_tokens(prompt)
        has_code = bool(CODE_PATTERN.search(prompt))
        reasoning = bool(REASONING_PATTERN.search(prompt))

        if policy.jev_enabled is False or not self.settings.jev_enabled:
            from app.decision import heuristic_route

            return heuristic_route(prompt, estimated_tokens=tokens)

        jev_result = self.jev.route_request(
            prompt=prompt,
            estimated_tokens=tokens,
            has_code=has_code,
            reasoning_requested=reasoning,
        )
        route = RouteDecision(
            route=jev_result.route if jev_result.route in ("small", "large") else "large",
            confidence=jev_result.confidence,
            source="jev" if jev_result.source == "jev" else "fallback",
        )
        return apply_route_confidence_policy(route)

    def model_name(self, route: str) -> str:
        if route == "small":
            return self.settings.small_model
        return self.settings.large_model
