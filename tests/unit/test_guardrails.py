from ops_copilot.guardrails import validate_finding
from ops_copilot.schemas import Finding


def test_valid_refs_pass_through():
    finding = Finding(
        hypotheses=["x"],
        recommended_action="y",
        confidence="medium",
        evidence_refs=["logs", "metrics"],
    )
    validated = validate_finding(finding, collected_evidence_keys={"logs", "metrics", "context"})
    assert validated.evidence_refs == ["logs", "metrics"]
    assert validated.insufficient_evidence is False


def test_fabricated_refs_are_stripped_and_downgraded():
    finding = Finding(
        hypotheses=["fabricated root cause"],
        recommended_action="y",
        confidence="high",
        evidence_refs=["logs", "runbooks"],
    )
    # only "metrics" was actually collected this run — logs/runbooks are fabricated
    validated = validate_finding(finding, collected_evidence_keys={"metrics"})
    assert validated.evidence_refs == []
    assert validated.insufficient_evidence is True
    assert validated.confidence == "low"


def test_partial_fabrication_keeps_valid_subset():
    finding = Finding(
        hypotheses=["x"],
        recommended_action="y",
        confidence="medium",
        evidence_refs=["logs", "runbooks"],
    )
    validated = validate_finding(finding, collected_evidence_keys={"logs"})
    assert validated.evidence_refs == ["logs"]
    assert validated.insufficient_evidence is False


def test_already_insufficient_finding_passes_through():
    finding = Finding(insufficient_evidence=True, evidence_refs=[])
    validated = validate_finding(finding, collected_evidence_keys={"logs", "metrics"})
    assert validated.insufficient_evidence is True
    assert validated.evidence_refs == []
