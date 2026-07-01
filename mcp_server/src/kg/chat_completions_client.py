"""走 chat.completions 的自定义 LLM client。

为什么需要它:Graphiti 默认的 OpenAIClient 用 OpenAI 新的 Responses API
(client.responses.parse)做结构化抽取。许多 OpenAI 兼容中转 / 国产端点
(right.codes 中转、智谱等)只实现了老的 chat.completions、不提供 /responses
端点,导致默认路径崩溃('str' object has no attribute 'output' 或 404)。

本 client 继承 BaseOpenAIClient(它已实现 generate_response 等上层逻辑),只重写
两个抽象方法,改用 chat.completions:
  - _create_completion: 普通 JSON 输出(response_format=json_object)
  - _create_structured_completion: 结构化输出。优先用 json_schema(更可靠);
    若端点不支持,降级为 json_object + 把 schema 注入 system 提示。
并重写 _handle_structured_response,按 chat.completions 的形状
(choices[0].message.content)解析,而非 Responses API 的 output_text。

参考契约(读自 graphiti-core 0.29.2 源码):
  _generate_response 把 _create_structured_completion 的返回交给
  _handle_structured_response;把 _create_completion 的返回交给
  _handle_json_response(读 choices[0].message.content / usage.prompt_tokens)。
"""

from __future__ import annotations

import json
import os
from typing import Any

from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_base_client import BaseOpenAIClient
from openai import AsyncOpenAI, BadRequestError, UnprocessableEntityError
from pydantic import BaseModel

# Graphiti's own retry path (is_server_or_retry_error) only recognizes
# httpx.HTTPStatusError, so it never retries the openai.InternalServerError(503)
# the SDK raises when dasuapi briefly overloads — the run just crashes. Letting
# AsyncOpenAI retry internally (it backs off on 408/409/429/5xx) is the backstop.
DEFAULT_MAX_RETRIES = 5


class ChatCompletionsClient(BaseOpenAIClient):
    """OpenAI-compatible client that uses chat.completions instead of Responses."""

    def __init__(
        self,
        config: LLMConfig | None = None,
        cache: bool = False,
        client: Any = None,
        max_tokens: int = 16384,
    ) -> None:
        super().__init__(config, cache=cache, max_tokens=max_tokens)
        cfg = config or LLMConfig()
        max_retries = int(os.environ.get("OPENAI_MAX_RETRIES", DEFAULT_MAX_RETRIES))
        self.client: AsyncOpenAI = client or AsyncOpenAI(
            api_key=cfg.api_key, base_url=cfg.base_url, max_retries=max_retries
        )

    async def _create_completion(
        self,
        model: str,
        messages: list[Any],
        temperature: float | None,
        max_tokens: int,
        response_model: type[BaseModel] | None = None,
    ) -> Any:
        """Plain JSON completion via chat.completions (json_object mode)."""
        return await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

    async def _create_structured_completion(
        self,
        model: str,
        messages: list[Any],
        temperature: float | None,
        max_tokens: int,
        response_model: type[BaseModel],
        reasoning: str | None = None,
        verbosity: str | None = None,
    ) -> Any:
        """Structured completion via chat.completions.

        Tries strict json_schema first. Only falls back to json_object (schema
        embedded in a system message) when the endpoint rejects the json_schema
        PARAMETER itself (400/422). Transient server errors (503/429/5xx) are
        NOT caught here — they propagate so AsyncOpenAI's max_retries and
        Graphiti's upper retry layer can handle them.

        Stashes the wrapper field name (if response_model is a single-list-field
        wrapper, as all Graphiti extraction models are) onto the returned object,
        so _handle_structured_response can re-wrap a bare-array response. Stored
        per-response (not on self) to stay safe under Graphiti's concurrency.
        """
        schema = response_model.model_json_schema()
        wrap_field = self._single_list_field(response_model)
        try:
            resp = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_model.__name__,
                        "schema": schema,
                        "strict": True,
                    },
                },
            )
        except (BadRequestError, UnprocessableEntityError):
            # Only fall back when the endpoint genuinely rejects the json_schema
            # PARAMETER (400/422). Do NOT fall back on 503/429/5xx/timeouts —
            # those are transient server errors that AsyncOpenAI(max_retries) has
            # already retried inside this create() call; swallowing them here and
            # retrying as json_object would (a) bypass that retry budget and
            # (b) on dasuapi return prose, not JSON (probe ② fails), so the run
            # crashes anyway. Let them propagate to Graphiti's upper retry layer.
            schema_hint = {
                "role": "system",
                "content": (
                    "You must reply with a single JSON object that conforms "
                    f"exactly to this JSON schema:\n{json.dumps(schema)}"
                ),
            }
            resp = await self.client.chat.completions.create(
                model=model,
                messages=[schema_hint, *messages],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        # Attach for the parser; per-response so concurrent calls don't collide.
        resp._kg_wrap_field = wrap_field  # type: ignore[attr-defined]
        return resp

    @staticmethod
    def _single_list_field(response_model: type[BaseModel]) -> str | None:
        """Return the field name if the model wraps exactly one list field, else None.

        Graphiti's extraction models (ExtractedEntities/ExtractedEdges/...) each
        wrap a single list field; that field name is the unambiguous target for
        re-wrapping a bare-array response.
        """
        fields = response_model.model_fields
        if len(fields) != 1:
            return None
        (name, field) = next(iter(fields.items()))
        origin = getattr(field.annotation, "__origin__", None)
        return name if origin in (list,) else None

    def _handle_structured_response(self, response: Any) -> tuple[dict[str, Any], int, int]:
        """Parse a chat.completions response (overrides the Responses-API parser).

        The base implementation reads response.output_text (Responses API). Our
        responses are chat.completions-shaped, so read choices[0].message.content
        and usage.prompt_tokens/completion_tokens instead.

        Normalization: some models drop the single-field wrapper and emit a bare
        JSON array instead of {"<field>": [...]}, which breaks Graphiti's
        Model(**resp). If we know the wrapper field (stashed in
        _create_structured_completion) and got a bare list, re-wrap it.
        """
        content = response.choices[0].message.content or ""
        input_tokens = 0
        output_tokens = 0
        if getattr(response, "usage", None):
            input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(response.usage, "completion_tokens", 0) or 0
        if not content:
            raise Exception(f"Invalid response from LLM: {response}")
        parsed = json.loads(content)
        if isinstance(parsed, list):
            wrap_field = getattr(response, "_kg_wrap_field", None)
            if wrap_field:
                parsed = {wrap_field: parsed}
        return parsed, input_tokens, output_tokens
