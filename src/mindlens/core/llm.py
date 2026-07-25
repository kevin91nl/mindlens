"""LLM client — wraps OpenRouter API."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    tool_calls: list = field(default_factory=list)


class LLMClient:
    """Thin wrapper around OpenRouter chat completions API."""

    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=120)

    def _headers(self) -> dict[str, str]:
        """Build compatible headers for local or hosted OpenAI-style APIs."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if "openrouter.ai" in self.base_url:
            headers["HTTP-Referer"] = "https://mindlens.local"
            headers["X-Title"] = "MindLens"
        return headers

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """Send a non-streaming chat completion request. Supports function calling."""
        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        resp = await self._client.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

        usage = data.get("usage", {})
        choice = data["choices"][0]["message"]
        content = choice.get("content") or ""
        reasoning = choice.get("reasoning") or ""

        # If no content but reasoning exists, extract final answer from reasoning
        if not content and reasoning:
            # Strip thinking tags if present
            import re
            content = re.sub(r'<thinking>.*?</thinking>', '', reasoning, flags=re.DOTALL).strip()
            if not content:
                # Use last paragraph of reasoning as the answer
                paragraphs = [p.strip() for p in reasoning.split('\n\n') if p.strip()]
                content = paragraphs[-1] if paragraphs else reasoning[-500:]
        tool_calls = choice.get("tool_calls") or []

        # Validate token counts — API sometimes returns 0 for valid requests
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        if input_tokens == 0 and output_tokens == 0 and content:
            # Estimate minimum tokens: ~4 chars per token for English text
            estimated_input = max(len(str(messages)) // 4, 1)
            estimated_output = max(len(content) // 4, 1)
            logger.warning(
                "Token count missing from API response, using estimates: input=%d, output=%d, model=%s",
                estimated_input, estimated_output, data.get("model", self.model),
            )
            input_tokens = estimated_input
            output_tokens = estimated_output

        return LLMResponse(
            content=content,
            model=data.get("model", self.model),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=usage.get("cost", 0.0),
            tool_calls=tool_calls,
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        """Yield SSE text deltas as they arrive. Handles both content and reasoning fields."""
        import json as _json

        try:
            async with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
                timeout=120,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    try:
                        data = _json.loads(payload)
                        delta = data["choices"][0].get("delta", {})
                        # Only send content to user, skip reasoning/thinking
                        text = delta.get("content") or ""
                        if not text:
                            continue
                        if text:
                            yield text
                    except (KeyError, IndexError, ValueError):
                        continue
        except Exception as exc:
            # Fallback: if streaming fails (e.g. model doesn't support it),
            # yield the complete response as a single chunk.
            logger.warning("Streaming failed (%s), falling back to non-streaming", exc)
            result = await self.complete(messages, temperature=temperature, max_tokens=max_tokens)
            if result.content:
                yield result.content

    async def close(self) -> None:
        await self._client.aclose()
