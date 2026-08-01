"""Agentic AI Operations Copilot.

An agentic assistant for on-call / support engineers: triages a ticket,
gathers logs/metrics/service-context evidence (in parallel), retrieves
relevant runbooks, and drafts an evidence-grounded root-cause hypothesis.

Public entry points:
    ops_copilot.graph.build_graph()   -> compiled LangGraph app
    ops_copilot.api.create_app()      -> FastAPI app
    ops_copilot.cli.app               -> Typer CLI
"""

__version__ = "1.0.0"
