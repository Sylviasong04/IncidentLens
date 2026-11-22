"""Minimal OhMyGPT OpenAI-compatible provider backed by the official OpenAI SDK."""

import asyncio
import os
import time
from uuid import uuid4

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, OpenAI

from incident_lens.llm.provider import LLMProvider, ProviderError
from incident_lens.llm.structured_output import (
    StructuredOutputError,
    output_messages,
    repair_message,
    strict_schema,
    validate_response,
)
from incident_lens.llm.usage import begin_request, record_usage

OHMYGPT_BASE_URL = "https://api.ohmygpt.com/v1"
DEFAULT_OHMYGPT_MODEL = "tencent/hy4-flash"
OHMYGPT_API_KEY_ENV = "OHMYGPT_API_KEY"


def _require_api_key(api_key: str | None = None) -> str:
    key = api_key if api_key is not None else os.getenv(OHMYGPT_API_KEY_ENV)
    if not isinstance(key, str) or not key.strip():
        raise ProviderError("PROVIDER_CONFIGURATION_REQUIRED")
    return key.strip()


def ohmygpt_sync_client(
    api_key: str | None = None,
    base_url: str = OHMYGPT_BASE_URL,
    timeout: float = 60.0,
) -> OpenAI:
    """Return a configured official OpenAI SDK client pointing at OhMyGPT."""
    return OpenAI(api_key=_require_api_key(api_key), base_url=base_url, timeout=timeout)


def ohmygpt_async_client(
    api_key: str | None = None,
    base_url: str = OHMYGPT_BASE_URL,
    timeout: float = 180.0,
) -> AsyncOpenAI:
    """Return a configured official AsyncOpenAI SDK client pointing at OhMyGPT."""
    return AsyncOpenAI(api_key=_require_api_key(api_key), base_url=base_url, timeout=timeout)


def quick_chat(
    prompt: str = "Hello",
    *,
    model: str = DEFAULT_OHMYGPT_MODEL,
    api_key: str | None = None,
    base_url: str = OHMYGPT_BASE_URL,
    timeout: float = 60.0,
) -> tuple[str, dict]:
    """Send a single short verification chat completion via the official OpenAI SDK."""
    client = ohmygpt_sync_client(api_key=api_key, base_url=base_url, timeout=timeout)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    reply = response.choices[0].message.content or ""
    meta = {
        "model": response.model,
        "finish_reason": response.choices[0].finish_reason,
        "usage": response.usage.model_dump() if response.usage else None,
    }
    return reply, meta


class OhMyGPTProvider(LLMProvider):
    """IncidentLens LLMProvider using the official OpenAI SDK against OhMyGPT."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        *,
        base_url: str = OHMYGPT_BASE_URL,
        temperature: float = 0.0,
        timeout: float = 180.0,
        structured_repair_retries: int = 1,
        response_format_mode: str = "json_object",
        thinking: str | None = None,
        client: AsyncOpenAI | None = None,
    ):
        self._api_key = _require_api_key(api_key)
        self.base_url = base_url.rstrip("/")
        self.model_id = model or os.getenv("OHMYGPT_MODEL") or DEFAULT_OHMYGPT_MODEL
        self.temperature = temperature
        self.timeout = timeout
        self.structured_repair_retries = structured_repair_retries
        if response_format_mode not in ("json_schema", "json_object"):
            raise ValueError("Unsupported response format")
        if thinking not in (None, "enabled", "disabled"):
            raise ValueError("Unsupported thinking setting")
        self.response_format_mode = response_format_mode
        self.thinking = thinking
        self._client = client
        self.recovery_snapshot = None
        self.stop_guard = None
        self.event_observer = None
        self.request_reconciler = None

    @property
    def model_parameters(self):
        return {
            "provider": "ohmygpt",
            "base_url": self.base_url,
            "model": self.model_id,
            "temperature": self.temperature,
            "response_format": self.response_format_mode,
            "thinking": self.thinking,
            "structured_repair_retries": self.structured_repair_retries,
            "request_timeout_seconds": self.timeout,
        }

    async def structured_call(self, role, system_prompt, user_payload, output_model):
        started = time.monotonic()
        logical_id = "logical-" + uuid4().hex
        usage = dict(
            source="model",
            model_id=self.model_id,
            llm_calls=0,
            actual_http_requests=0,
            logical_structured_calls=1,
            logical_call_id=logical_id,
            transport_retries=0,
            repair_requests=0,
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            measured_total_tokens=0,
            tokens_complete=True,
            provider_recovery_enabled=True,
            provider_attempts=[],
        )
        schema = strict_schema(output_model)
        messages = output_messages(system_prompt, user_payload, schema)
        response_format = (
            {"type": "json_object"}
            if self.response_format_mode == "json_object"
            else {
                "type": "json_schema",
                "json_schema": {
                    "name": output_model.__name__,
                    "strict": True,
                    "schema": schema,
                },
            }
        )
        client = self._client or ohmygpt_async_client(
            api_key=self._api_key, base_url=self.base_url, timeout=self.timeout
        )
        close_client = self._client is None
        try:
            for attempt in range(self.structured_repair_retries + 1):
                permit = None
                if self.request_guard is not None:
                    try:
                        permit = self.request_guard()
                    except RuntimeError:
                        raise ProviderError("REQUEST_BUDGET_EXCEEDED", usage) from None
                usage["llm_calls"] += 1
                usage["actual_http_requests"] += 1
                begin_request(usage)
                request_kwargs = dict(
                    model=self.model_id,
                    temperature=self.temperature,
                    messages=messages,
                    response_format=response_format,
                )
                if self.thinking is not None:
                    request_kwargs["extra_body"] = {"thinking": {"type": self.thinking}}
                completion = None
                for t_try in range(3):
                    try:
                        completion = await client.chat.completions.create(**request_kwargs)
                        break
                    except APITimeoutError:
                        if t_try < 2:
                            usage["transport_retries"] += 1
                            await asyncio.sleep(2.0 * (t_try + 1))
                            continue
                        if self.request_reconciler is not None:
                            self.request_reconciler(permit, None)
                        raise ProviderError("PROVIDER_TIMEOUT", usage) from None
                    except APIConnectionError:
                        if t_try < 2:
                            usage["transport_retries"] += 1
                            await asyncio.sleep(2.0 * (t_try + 1))
                            continue
                        if self.request_reconciler is not None:
                            self.request_reconciler(permit, None)
                        raise ProviderError("PROVIDER_TRANSPORT_ERROR", usage) from None
                    except APIStatusError as exc:
                        if exc.status_code in {429, 500, 502, 503, 504} and t_try < 2:
                            usage["transport_retries"] += 1
                            await asyncio.sleep(2.0 * (t_try + 1))
                            continue
                        if self.request_reconciler is not None:
                            self.request_reconciler(permit, None)
                        raise ProviderError("PROVIDER_HTTP_ERROR", usage) from None

                raw = completion.model_dump(mode="json")
                total = record_usage(usage, raw.get("usage"))
                if total is not None and self.token_observer is not None:
                    self.token_observer(total)
                if self.request_reconciler is not None:
                    self.request_reconciler(
                        permit, total if type(total) is int and total >= 0 else None
                    )
                try:
                    parsed = validate_response(raw, output_model)
                    usage["elapsed_ms"] = (time.monotonic() - started) * 1000
                    return parsed, usage
                except StructuredOutputError as exc:
                    usage["provider_attempts"].append(
                        dict(
                            event_type="PROVIDER_FAILURE_CLASSIFIED",
                            logical_call_id=logical_id,
                            http_attempt_index=usage["llm_calls"],
                            category=exc.category,
                            phase=exc.phase,
                            validation_summary=exc.summary,
                            output_model=output_model.__name__,
                        )
                    )
                    if not exc.repairable or attempt >= self.structured_repair_retries:
                        usage["elapsed_ms"] = (time.monotonic() - started) * 1000
                        raise ProviderError("STRUCTURED_OUTPUT_INVALID", usage) from None
                    usage["repair_requests"] += 1
                    messages.append({"role": "user", "content": repair_message(exc)})
        finally:
            if close_client:
                await client.close()
