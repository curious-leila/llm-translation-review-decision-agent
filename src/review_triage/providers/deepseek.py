"""DeepSeek OpenAI-compatible adapter with strict JSON/Pydantic validation."""

from __future__ import annotations

import json
import os
import random
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from review_triage.prompts import RenderedEvaluatorPrompt, RenderedStructuredPrompt


PROVIDER_NAME = "deepseek"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 0.5
DEFAULT_MAX_TOKENS = 4096
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class DeepSeekConfigurationError(ValueError):
    """The environment does not contain a safe, usable DeepSeek configuration."""


class DeepSeekProviderError(RuntimeError):
    """A sanitized provider error safe for execution logs and exceptions."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True, repr=False)
class DeepSeekConfig:
    """Non-secret runtime configuration; ``api_key`` must never be serialized."""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS
    max_tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = ".env",
        override: bool = False,
    ) -> "DeepSeekConfig":
        if env_file is not None:
            load_dotenv(dotenv_path=env_file, override=override)
        return cls(
            api_key=_required_env("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).strip(),
            model=os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL).strip(),
            timeout_seconds=_float_env(
                "DEEPSEEK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS, minimum=0.1
            ),
            max_retries=_int_env("DEEPSEEK_MAX_RETRIES", DEFAULT_MAX_RETRIES, minimum=0),
            retry_backoff_seconds=_float_env(
                "DEEPSEEK_RETRY_BACKOFF_SECONDS",
                DEFAULT_RETRY_BACKOFF_SECONDS,
                minimum=0.0,
            ),
            max_tokens=_int_env(
                "DEEPSEEK_MAX_TOKENS", DEFAULT_MAX_TOKENS, minimum=1
            ),
        )

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise DeepSeekConfigurationError("DEEPSEEK_API_KEY is required")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise DeepSeekConfigurationError(
                "DEEPSEEK_BASE_URL must be an absolute HTTPS URL without query/fragment"
            )
        if not self.model:
            raise DeepSeekConfigurationError("DEEPSEEK_MODEL must not be empty")
        if self.timeout_seconds <= 0:
            raise DeepSeekConfigurationError("timeout_seconds must be positive")
        if self.max_retries < 0:
            raise DeepSeekConfigurationError("max_retries must be non-negative")
        if self.retry_backoff_seconds < 0:
            raise DeepSeekConfigurationError(
                "retry_backoff_seconds must be non-negative"
            )
        if self.max_tokens <= 0:
            raise DeepSeekConfigurationError("max_tokens must be positive")

    @property
    def endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    def public_metadata(self) -> dict[str, Any]:
        """Return auditable configuration while deliberately excluding the API key."""

        return {
            "provider_name": PROVIDER_NAME,
            "model": self.model,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "retry_backoff_seconds": self.retry_backoff_seconds,
            "max_tokens": self.max_tokens,
            "structured_output_mode": "json_object_then_pydantic",
        }

    def __repr__(self) -> str:
        return f"DeepSeekConfig({self.public_metadata()!r})"


class DeepSeekProvider:
    """Synchronous provider-neutral adapter implementing ``StructuredLLM``."""

    provider_name = PROVIDER_NAME

    def __init__(
        self,
        config: DeepSeekConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self.config = config
        self._sleeper = sleeper
        self._random_source = random_source
        self._client = httpx.Client(
            timeout=httpx.Timeout(config.timeout_seconds),
            transport=transport,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "review-triage-agent/0.1",
            },
        )
        self._last_response_model: str | None = None
        self._api_request_count = 0

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = ".env",
        override: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> "DeepSeekProvider":
        return cls(
            DeepSeekConfig.from_env(env_file=env_file, override=override),
            transport=transport,
        )

    @property
    def model_version(self) -> str:
        return self._last_response_model or self.config.model

    @property
    def public_metadata(self) -> dict[str, Any]:
        metadata = self.config.public_metadata()
        metadata["response_model"] = self._last_response_model
        metadata["api_request_count"] = self._api_request_count
        return metadata

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "DeepSeekProvider":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def invoke_structured(
        self,
        *,
        prompt_version: str,
        payload: Mapping[str, Any],
        output_schema: type[BaseModel],
        prompt: RenderedEvaluatorPrompt | RenderedStructuredPrompt | None = None,
    ) -> Mapping[str, Any]:
        del payload  # The frozen rendered prompt is the only provider-facing content.
        if prompt is None:
            raise DeepSeekProviderError(
                "PROVIDER_PROMPT_MISSING",
                "DeepSeek invocation requires a versioned rendered Prompt artifact",
            )
        if prompt.prompt_version != prompt_version:
            raise DeepSeekProviderError(
                "PROVIDER_PROMPT_VERSION_MISMATCH",
                "Rendered Prompt version does not match the invocation version",
            )
        body = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": prompt.system_prompt},
                {"role": "user", "content": prompt.user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
            "max_tokens": self.config.max_tokens,
        }
        response_data, content = self._post_with_retries(body)
        decoded = _decode_structured_content(content)
        try:
            validated = output_schema.model_validate(decoded)
        except ValidationError as error:
            safe_violations = [
                {
                    "location": ".".join(str(part) for part in item["loc"]),
                    "type": item["type"],
                    "validation_message": item["msg"],
                }
                for item in error.errors(include_url=False, include_context=False)
            ]
            raise DeepSeekProviderError(
                "PROVIDER_SCHEMA_MISMATCH",
                "DeepSeek JSON did not satisfy the requested structured schema; "
                f"violations={json.dumps(safe_violations, sort_keys=True)}",
            ) from error
        return validated.model_dump(mode="json")

    def _post_with_retries(
        self, body: Mapping[str, Any]
    ) -> tuple[Mapping[str, Any], str]:
        for attempt in range(self.config.max_retries + 1):
            try:
                self._api_request_count += 1
                response = self._client.post(self.config.endpoint, json=body)
            except httpx.TimeoutException as error:
                if attempt < self.config.max_retries:
                    self._wait_before_retry(attempt, None)
                    continue
                raise DeepSeekProviderError(
                    "PROVIDER_TIMEOUT",
                    "DeepSeek request timed out after configured retries",
                    retryable=True,
                ) from error
            except httpx.RequestError as error:
                if attempt < self.config.max_retries:
                    self._wait_before_retry(attempt, None)
                    continue
                raise DeepSeekProviderError(
                    "PROVIDER_NETWORK_ERROR",
                    "DeepSeek network request failed after configured retries",
                    retryable=True,
                ) from error

            if response.status_code < 400:
                response_data = self._decode_response(response)
                response_model = response_data.get("model")
                if isinstance(response_model, str) and response_model.strip():
                    self._last_response_model = response_model.strip()
                try:
                    content = self._extract_content(response_data)
                except DeepSeekProviderError as error:
                    if (
                        error.code == "PROVIDER_EMPTY_CONTENT"
                        and attempt < self.config.max_retries
                    ):
                        self._wait_before_retry(attempt, response)
                        continue
                    raise
                return response_data, content
            retryable = response.status_code in RETRYABLE_STATUS_CODES
            if retryable and attempt < self.config.max_retries:
                self._wait_before_retry(attempt, response)
                continue
            code = (
                "PROVIDER_RATE_LIMIT"
                if response.status_code == 429
                else "PROVIDER_AUTH_FAILURE"
                if response.status_code == 401
                else "PROVIDER_HTTP_ERROR"
            )
            raise DeepSeekProviderError(
                code,
                f"DeepSeek request failed with HTTP {response.status_code}",
                status_code=response.status_code,
                retryable=retryable,
            )
        raise AssertionError("retry loop must return or raise")

    def _wait_before_retry(
        self, attempt: int, response: httpx.Response | None
    ) -> None:
        retry_after = _safe_retry_after(response)
        if retry_after is not None:
            delay = retry_after
        else:
            jitter = 0.5 + self._random_source() * 0.5
            delay = self.config.retry_backoff_seconds * (2**attempt) * jitter
        self._sleeper(delay)

    @staticmethod
    def _decode_response(response: httpx.Response) -> Mapping[str, Any]:
        try:
            decoded = response.json()
        except (json.JSONDecodeError, ValueError) as error:
            raise DeepSeekProviderError(
                "PROVIDER_INVALID_RESPONSE",
                "DeepSeek returned a non-JSON HTTP response",
            ) from error
        if not isinstance(decoded, Mapping):
            raise DeepSeekProviderError(
                "PROVIDER_INVALID_RESPONSE",
                "DeepSeek response body was not a JSON object",
            )
        return decoded

    @staticmethod
    def _extract_content(response_data: Mapping[str, Any]) -> str:
        try:
            content = response_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise DeepSeekProviderError(
                "PROVIDER_INVALID_RESPONSE",
                "DeepSeek response omitted assistant message content",
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise DeepSeekProviderError(
                "PROVIDER_EMPTY_CONTENT",
                "DeepSeek returned empty assistant content",
            )
        return content


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise DeepSeekConfigurationError(f"{name} is required")
    return value.strip()


def _float_env(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise DeepSeekConfigurationError(f"{name} must be numeric") from error
    if value < minimum:
        raise DeepSeekConfigurationError(f"{name} must be >= {minimum}")
    return value


def _int_env(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise DeepSeekConfigurationError(f"{name} must be an integer") from error
    if value < minimum:
        raise DeepSeekConfigurationError(f"{name} must be >= {minimum}")
    return value


def _safe_retry_after(response: httpx.Response | None) -> float | None:
    if response is None:
        return None
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return min(max(value, 0.0), 60.0)


_SINGLE_JSON_FENCE = re.compile(
    r"\A\s*```(?:json)?\s*\r?\n(?P<body>[\s\S]*?)\r?\n```\s*\Z",
    flags=re.IGNORECASE,
)


def _decode_structured_content(content: str) -> Any:
    """Decode a JSON object, tolerating only one prose-free JSON code fence.

    Some OpenAI-compatible JSON-mode models wrap the otherwise valid object in
    a Markdown fence. The compatibility boundary stays deliberately narrow:
    explanatory prose, multiple fences, or malformed JSON remain explicit
    provider failures, and Pydantic validation still owns the output contract.
    """

    candidate = content.strip()
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, TypeError, ValueError) as first_error:
        fenced = _SINGLE_JSON_FENCE.fullmatch(candidate)
        if fenced is None:
            raise DeepSeekProviderError(
                "PROVIDER_INVALID_JSON",
                "DeepSeek returned malformed JSON content",
            ) from first_error
        try:
            return json.loads(fenced.group("body").strip())
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise DeepSeekProviderError(
                "PROVIDER_INVALID_JSON",
                "DeepSeek returned malformed JSON content",
            ) from error
