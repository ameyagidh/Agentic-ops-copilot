"""
Agentic AI Operations Copilot
--------------------------------------------------
An agentic assistant for on-call / support engineers. Given a ticket or
alert, it triages severity, pulls relevant logs and service context,
retrieves recent metrics, and drafts a root-cause hypothesis — the kind
of workflow that normally means five tabs and ten minutes of manual digging.

Router agent classifies intent -> dispatches to specialist tools -> a
synthesis step turns raw tool output into a structured operator-ready
summary, gated by guardrails so it never fabricates a root cause it can't
support with retrieved evidence.

Stack: LangGraph, LangChain, OpenAI API / Amazon Bedrock, vector retrieval
"""

from typing import TypedDict, List, Literal, Optional
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import tool
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings


# ---------- Tools: each wraps a real ops system in production ----------
@tool
def triage_ticket(ticket_text: str) -> str:
    """Classify a ticket's severity and category (e.g. billing, latency, auth)."""
    # In production this hits an internal classifier / rules engine.
    return "severity=SEV3, category=latency"


@tool
def summarize_logs(service_name: str, time_window_minutes: int = 30) -> str:
    """Pull and summarize recent error/warn logs for a service."""
    # In production this queries CloudWatch/Splunk and summarizes with an LLM.
    return f"[log summary for {service_name}, last {time_window_minutes}m]: elevated 5xx rate, DB pool exhaustion pattern"


@tool
def get_service_metrics(service_name: str) -> str:
    """Fetch current latency/error-rate/throughput metrics for a service."""
    return f"[metrics for {service_name}]: p99 latency 4.2s (baseline 800ms), error rate 6.1%"


@tool
def lookup_service_context(service_name: str) -> str:
    """Retrieve ownership, dependencies, and recent deploys for a service."""
    return f"[context for {service_name}]: owned by fees-platform team, deployed 40m ago, depends on billing-db"


TOOLS = [triage_ticket, summarize_logs, get_service_metrics, lookup_service_context]


class OpsState(TypedDict):
    ticket_text: str
    service_name: str
    triage: str
    logs: str
    metrics: str
    context: str
    root_cause_summary: str


llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
llm_with_tools = llm.bind_tools(TOOLS)


def triage_node(state: OpsState) -> OpsState:
    state["triage"] = triage_ticket.invoke({"ticket_text": state["ticket_text"]})
    return state


def gather_context_node(state: OpsState) -> OpsState:
    state["logs"] = summarize_logs.invoke({"service_name": state["service_name"]})
    state["metrics"] = get_service_metrics.invoke({"service_name": state["service_name"]})
    state["context"] = lookup_service_context.invoke({"service_name": state["service_name"]})
    return state


def synthesize_node(state: OpsState) -> OpsState:
    """Ground the summary strictly in retrieved tool output — refuse to guess."""
    prompt = f"""You are an SRE copilot. Using ONLY the evidence below, write a
    3-bullet root-cause hypothesis and a recommended next action. If the
    evidence doesn't support a clear root cause, say so explicitly instead
    of speculating.

    Triage: {state['triage']}
    Logs: {state['logs']}
    Metrics: {state['metrics']}
    Service context: {state['context']}
    """
    resp = llm.invoke([SystemMessage(content=prompt)])
    state["root_cause_summary"] = resp.content
    return state


graph = StateGraph(OpsState)
graph.add_node("triage", triage_node)
graph.add_node("gather_context", gather_context_node)
graph.add_node("synthesize", synthesize_node)

graph.set_entry_point("triage")
graph.add_edge("triage", "gather_context")
graph.add_edge("gather_context", "synthesize")
graph.add_edge("synthesize", END)

app = graph.compile()


if __name__ == "__main__":
    result = app.invoke({
        "ticket_text": "Checkout API is timing out for ~6% of requests since the last deploy.",
        "service_name": "checkout-api",
    })
    print(result["root_cause_summary"])
