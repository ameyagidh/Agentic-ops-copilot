# Agentic-ops-copilot

# agentic-ops-copilot

**Agentic AI Operations Copilot** — an AI agent for on-call/support engineers that triages a ticket, gathers logs/metrics/service context in parallel, and drafts a grounded root-cause hypothesis instead of a human doing it manually across five tabs.

## Summary
Given an incoming ticket or alert, the copilot classifies severity and category, then dispatches to specialist tools that pull recent error logs, live latency/error-rate metrics, and service ownership/deploy context. A synthesis step turns that raw evidence into a 3-bullet root-cause hypothesis with a recommended next action — with an explicit guardrail to say "insufficient evidence" rather than speculate.

## Architecture
```
Ticket -> Triage -> [Logs | Metrics | Service Context] (parallel) -> Synthesize -> Root-cause summary
```
Built as a LangGraph state machine (`StateGraph`) with each stage as a node and tool calls wrapping real ops systems (CloudWatch/Splunk-style log summarization, metrics APIs, service-ownership lookup).

## Stack
- LangGraph, LangChain
- OpenAI API / Amazon Bedrock
- Vector retrieval for context grounding

## Why it matters
Mirrors the shape of an AI support agent grounded strictly in retrieved evidence — the same pattern used in production for Amazon's internal "Fees Assistant" Slack bot (Bedrock Agent + Kendra GenAI Index), which cut support response time from a 24-hour SLA to near-instant self-service.

## Run
```bash
python agentic_ops_copilot.py
```
