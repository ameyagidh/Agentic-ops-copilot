"""Lazy LLM provider factory.

The single most important property of this module: **importing it must
never require credentials or network access, and never construct a real
client at import time.** The previous prototype built ``ChatOpenAI(...)`` at
module scope, so simply importing the package crashed without
``OPENAI_API_KEY``. Every provider client here is built lazily, inside
``get_chat_model``, and provider SDKs are imported inside their own branch so
missing optional extras never break the base import.
"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from ops_copilot.config import Settings
from ops_copilot.schemas import Finding


class FakeChatModel(BaseChatModel):
    """A deterministic, dependency-free chat model used as the default
    provider so the entire system — graph, API, and test suite — runs with
    zero API keys and zero network access.

    ``with_structured_output`` is explicitly overridden rather than relying
    on the ``BaseChatModel`` default. LangChain's default implementation is
    built on top of ``bind_tools``/tool-calling; a minimal fake that only
    implements ``_generate`` either raises or returns a message with no
    ``tool_calls``, so the default would silently produce nothing. Since this
    is the default provider, every offline code path — including the whole
    test suite — depends on this override actually working.
    """

    model_name: str = "fake-deterministic-v1"

    @property
    def _llm_type(self) -> str:
        return "fake-ops-copilot"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        text = "\n".join(getattr(m, "content", "") for m in messages)
        message = AIMessage(content=f"[fake-llm] synthesized response for prompt of {len(text)} chars")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def with_structured_output(self, schema: dict[Any, Any] | type, **kwargs: Any) -> Runnable[Any, Any]:
        if schema is not Finding:
            # Generic fallback: return an empty-ish instance of whatever schema
            # was requested, so callers using other schemas don't crash.
            def _generic(_input: Any) -> Any:
                if isinstance(schema, type) and issubclass(schema, BaseModel):
                    return schema.model_construct()
                return {}

            return RunnableLambda(_generic)

        def _build_finding(input_value: Any) -> Finding:
            prompt_text = _messages_to_text(input_value)
            return _fake_finding_from_evidence(prompt_text)

        return RunnableLambda(_build_finding)


def _messages_to_text(input_value: Any) -> str:
    if isinstance(input_value, str):
        return input_value
    if isinstance(input_value, list):
        return "\n".join(getattr(m, "content", str(m)) for m in input_value)
    return str(input_value)


def _fake_finding_from_evidence(prompt_text: str) -> Finding:
    """Builds a plausible, evidence-grounded ``Finding`` purely from the text
    of the prompt — no network call. This lets the fake provider exercise
    the real guardrail-validation code path (evidence_refs must resolve to
    evidence actually collected) rather than returning a static stub.
    """
    refs: list[str] = []
    if re.search(r"Logs:\s*(?!none|no evidence)", prompt_text, re.IGNORECASE):
        refs.append("logs")
    if re.search(r"Metrics:\s*(?!none|no evidence)", prompt_text, re.IGNORECASE):
        refs.append("metrics")
    if re.search(r"(Service context|Context):\s*(?!none|no evidence)", prompt_text, re.IGNORECASE):
        refs.append("context")
    if re.search(r"Runbooks?:\s*(?!none|no evidence)", prompt_text, re.IGNORECASE):
        refs.append("runbooks")

    no_notable_signal = bool(
        re.search(r"within normal bounds|no notable error|no error/warn lines found", prompt_text, re.IGNORECASE)
    )
    if not refs or no_notable_signal:
        return Finding(
            hypotheses=[],
            recommended_action="Gather additional logs/metrics before drawing a conclusion.",
            confidence="low",
            evidence_refs=[],
            insufficient_evidence=True,
            explanation="Fake model: available evidence did not clearly support a root cause.",
        )

    hypotheses = ["Elevated error rate correlates with a recent change to a dependency."]
    if "pool exhaustion" in prompt_text.lower() or "db pool" in prompt_text.lower():
        hypotheses = ["Database connection pool exhaustion is driving elevated latency and 5xx errors."]
    elif "deploy" in prompt_text.lower():
        hypotheses = ["The most recent deploy introduced a regression correlated with the error spike."]

    return Finding(
        hypotheses=hypotheses,
        recommended_action=(
            "Roll back the most recent deploy if the timing correlates; "
            "scale the affected resource pool as a mitigation."
        ),
        confidence="medium",
        evidence_refs=refs,
        insufficient_evidence=False,
        explanation="Fake model: hypothesis derived deterministically from retrieved evidence for offline/dev use.",
    )


def _build_openai_model(settings: Settings) -> BaseChatModel:
    from langchain_openai import ChatOpenAI  # imported lazily: optional extra

    kwargs: dict[str, Any] = {"model": settings.llm_model, "temperature": settings.llm_temperature}
    if settings.openai_api_key:
        kwargs["api_key"] = settings.openai_api_key
    return ChatOpenAI(**kwargs)


def _build_bedrock_model(settings: Settings) -> BaseChatModel:
    from langchain_aws import ChatBedrockConverse  # imported lazily: optional extra

    return ChatBedrockConverse(
        model=settings.llm_model,
        region_name=settings.bedrock_region,
        temperature=settings.llm_temperature,
    )


_model_cache: dict[tuple[str, str, float], BaseChatModel] = {}


def get_chat_model(settings: Settings) -> BaseChatModel:
    """Lazily construct (and cache) the chat model for the configured
    provider. Never called at import time — only when a graph run actually
    needs a model. Cached by the settings fields that actually affect the
    client (``Settings`` itself isn't hashable, so we key on a plain tuple).
    """
    cache_key = (settings.llm_provider, settings.llm_model, settings.llm_temperature)
    if cache_key in _model_cache:
        return _model_cache[cache_key]

    if settings.llm_provider == "openai":
        model = _build_openai_model(settings)
    elif settings.llm_provider == "bedrock":
        model = _build_bedrock_model(settings)
    else:
        model = FakeChatModel()

    _model_cache[cache_key] = model
    return model
