"""Proves the offline test suite can exist at all: the fake provider's
with_structured_output must actually return a valid Finding, since it's the
default provider every offline code path depends on.
"""

import pytest

from ops_copilot.llm import FakeChatModel, get_chat_model
from ops_copilot.schemas import Finding


def test_fake_model_is_default(settings_factory):
    settings = settings_factory()
    model = get_chat_model(settings)
    assert isinstance(model, FakeChatModel)


@pytest.mark.asyncio
async def test_fake_structured_output_grounded_case(settings_factory):
    settings = settings_factory()
    model = get_chat_model(settings)
    structured = model.with_structured_output(Finding)
    prompt = (
        "Triage: severity=SEV2, category=latency\n"
        "Logs: [log summary]: db pool exhaustion detected\n"
        "Metrics: p99 latency 4200ms\n"
        "Service context: owned by team-x\n"
        "Runbooks: none retrieved"
    )
    finding = await structured.ainvoke(prompt)
    assert isinstance(finding, Finding)
    assert finding.insufficient_evidence is False
    assert finding.evidence_refs
    assert finding.hypotheses


@pytest.mark.asyncio
async def test_fake_structured_output_insufficient_case(settings_factory):
    settings = settings_factory()
    model = get_chat_model(settings)
    structured = model.with_structured_output(Finding)
    prompt = (
        "Triage: severity=SEV4, category=unknown\n"
        "Logs: within normal bounds; no notable error patterns\n"
        "Metrics: none — not collected for this category\n"
        "Service context: none\n"
        "Runbooks: none retrieved"
    )
    finding = await structured.ainvoke(prompt)
    assert finding.insufficient_evidence is True
    assert finding.evidence_refs == []


def test_get_chat_model_is_cached(settings_factory):
    settings = settings_factory()
    model_a = get_chat_model(settings)
    model_b = get_chat_model(settings)
    assert model_a is model_b
