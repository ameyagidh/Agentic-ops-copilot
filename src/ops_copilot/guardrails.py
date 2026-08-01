"""Evidence-grounding enforcement.

The previous prototype's guardrail was prompt text only ("use ONLY the
evidence below... don't speculate") with nothing checking that the model
actually complied. Here, ``validate_finding`` programmatically checks that
every ``evidence_refs`` entry the model cites resolves to evidence that was
actually collected during this run. Anything else is stripped, and a
finding with no valid refs left is downgraded to ``insufficient_evidence``
rather than shipped as a confident, unsupported root cause.
"""

from __future__ import annotations

from ops_copilot.schemas import Finding

VALID_EVIDENCE_KEYS = {"logs", "metrics", "context", "runbooks"}


def validate_finding(finding: Finding, collected_evidence_keys: set[str]) -> Finding:
    """Returns a corrected copy of ``finding`` with any evidence_refs that
    don't correspond to evidence collected this run removed. If nothing
    survives, the finding is downgraded to insufficient_evidence.
    """
    allowed = VALID_EVIDENCE_KEYS & collected_evidence_keys
    valid_refs = [ref for ref in finding.evidence_refs if ref in allowed]

    if valid_refs and not finding.insufficient_evidence:
        return finding.model_copy(update={"evidence_refs": valid_refs})

    if not valid_refs and not finding.insufficient_evidence:
        return finding.model_copy(
            update={
                "evidence_refs": [],
                "insufficient_evidence": True,
                "confidence": "low",
                "explanation": (
                    finding.explanation + " [guardrail: original evidence_refs did not resolve to evidence "
                    "actually collected this run; downgraded to insufficient_evidence]"
                ).strip(),
            }
        )

    return finding.model_copy(update={"evidence_refs": valid_refs})
