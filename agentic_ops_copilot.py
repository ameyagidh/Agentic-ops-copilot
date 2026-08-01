"""Deprecated entry point — kept so ``python agentic_ops_copilot.py`` (as
documented in earlier versions of this project) keeps working on a bare
clone. The real implementation now lives in the ``ops_copilot`` package
under ``src/`` (see README.md). Prefer:

    pip install -e .
    ops-copilot analyze "<ticket text>" --service <service-name>

or ``ops-copilot serve`` for the API + dashboard.
"""

import asyncio
import sys
from pathlib import Path

# Allow running this script directly from a bare clone, before `pip install -e .`
# has put `src/ops_copilot` on sys.path.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ops_copilot.graph import build_graph, close_graph  # noqa: E402
from ops_copilot.schemas import IncidentRequest  # noqa: E402


async def _main() -> None:
    graph = await build_graph()
    try:
        result = await graph.ainvoke(
            {
                "incident": IncidentRequest(
                    ticket_text="Checkout API is timing out for ~6% of requests since the last deploy.",
                    service_name="checkout-api",
                )
            },
            config={"configurable": {"thread_id": "demo"}},
        )
    finally:
        await close_graph(graph)

    finding = result["finding"]
    if finding.insufficient_evidence:
        print(f"Insufficient evidence: {finding.explanation}")
    else:
        for hypothesis in finding.hypotheses:
            print(f"- {hypothesis}")
        print(f"\nRecommended action: {finding.recommended_action}")
        print(f"Confidence: {finding.confidence} (evidence: {', '.join(finding.evidence_refs)})")


if __name__ == "__main__":
    asyncio.run(_main())
