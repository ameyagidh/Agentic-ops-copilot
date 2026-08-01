"""Typed data contracts shared across tools, graph, guardrails, and API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["SEV1", "SEV2", "SEV3", "SEV4"]
Category = Literal["latency", "errors", "billing", "auth", "deployment", "unknown"]
Confidence = Literal["low", "medium", "high"]


class IncidentRequest(BaseModel):
    """Inbound request: a ticket/alert plus the service it concerns."""

    ticket_text: str = Field(..., min_length=1, max_length=4000)
    service_name: str = Field(..., min_length=1, max_length=200)


class Triage(BaseModel):
    severity: Severity
    category: Category
    rationale: str = ""


class LogEvidence(BaseModel):
    service_name: str
    window_minutes: int
    summary: str
    error_signatures: list[str] = Field(default_factory=list)


class MetricEvidence(BaseModel):
    service_name: str
    p99_latency_ms: float
    baseline_latency_ms: float
    error_rate_pct: float
    throughput_rps: float


class ServiceContext(BaseModel):
    service_name: str
    owner_team: str
    dependencies: list[str] = Field(default_factory=list)
    last_deploy_minutes_ago: int | None = None
    recent_change_summary: str | None = None


class RunbookExcerpt(BaseModel):
    title: str
    snippet: str
    source: str


class Finding(BaseModel):
    """The structured, evidence-grounded output of the synthesis step."""

    hypotheses: list[str] = Field(default_factory=list)
    recommended_action: str = ""
    confidence: Confidence = "low"
    evidence_refs: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False
    explanation: str = ""


class RunRecord(BaseModel):
    """A full, persisted run of the copilot graph — what the API/UI show."""

    run_id: str
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    incident: IncidentRequest
    triage: Triage | None = None
    logs: LogEvidence | None = None
    metrics: MetricEvidence | None = None
    context: ServiceContext | None = None
    runbooks: list[RunbookExcerpt] = Field(default_factory=list)
    finding: Finding | None = None
    error: str | None = None
    created_at: str
    updated_at: str
