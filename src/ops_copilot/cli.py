"""Typer CLI. Preserves the original ``python agentic_ops_copilot.py``
one-shot demo behavior (``ops-copilot analyze``) and adds ``serve``/``backends``.
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.panel import Panel

from ops_copilot.config import get_settings
from ops_copilot.graph import build_graph, close_graph
from ops_copilot.schemas import IncidentRequest

app = typer.Typer(help="Agentic AI Operations Copilot")
console = Console()


@app.command()
def analyze(
    ticket_text: str = typer.Argument(..., help="The incident ticket/alert text."),
    service: str = typer.Option(..., "--service", "-s", help="The affected service name."),
) -> None:
    """Run one incident through the copilot graph and print the finding."""

    async def _run() -> None:
        settings = get_settings()
        graph = await build_graph(settings)
        try:
            result = await graph.ainvoke(
                {"incident": IncidentRequest(ticket_text=ticket_text, service_name=service)},
                config={"configurable": {"thread_id": f"cli-{service}"}},
            )
        finally:
            await close_graph(graph)

        triage = result["triage"]
        finding = result["finding"]
        console.print(Panel(f"severity={triage.severity}  category={triage.category}", title="Triage"))
        if finding.insufficient_evidence:
            console.print(Panel(finding.explanation, title="Insufficient evidence", style="yellow"))
        else:
            body = "\n".join(f"- {h}" for h in finding.hypotheses)
            body += f"\n\nRecommended action: {finding.recommended_action}"
            body += f"\nConfidence: {finding.confidence}  |  Evidence: {', '.join(finding.evidence_refs)}"
            console.print(Panel(body, title="Root-cause hypothesis"))

    asyncio.run(_run())


@app.command()
def backends() -> None:
    """Print the resolved configuration (provider, backends, ports)."""
    settings = get_settings()
    console.print_json(data=settings.model_dump(exclude={"openai_api_key", "aws_secret_access_key", "api_key"}))


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host."),
    port: int = typer.Option(8000, help="Bind port."),
    reload: bool = typer.Option(False, help="Enable autoreload (development only)."),
) -> None:
    """Run the FastAPI service (REST API + embedded dashboard)."""
    import uvicorn

    uvicorn.run("ops_copilot.api:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
