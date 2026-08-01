# Project documentation: Agentic Ops Copilot

This document explains **everything done in this project**, in depth: what existed before, what was broken, every change made and why it was shaped the way it was, how the system is verified, and what's still honestly unverified. It's meant to be read alongside the [README](../README.md), which covers day-to-day usage; this document covers the engineering story.

## Table of contents

1. [Starting point](#1-starting-point)
2. [What "production ready" meant here](#2-what-production-ready-meant-here)
3. [Defects fixed and why the fixes are shaped this way](#3-defects-fixed-and-why-the-fixes-are-shaped-this-way)
4. [Architecture, end to end](#4-architecture-end-to-end)
5. [Every module, what it does and why it exists](#5-every-module-what-it-does-and-why-it-exists)
6. [The adapter seam — how to extend this](#6-the-adapter-seam--how-to-extend-this)
7. [The GUI](#7-the-gui)
8. [Observability](#8-observability)
9. [Docker and CI](#9-docker-and-ci)
10. [Testing strategy and what was actually verified](#10-testing-strategy-and-what-was-actually-verified)
11. [Second hardening pass — what was added after the first release](#11-second-hardening-pass--what-was-added-after-the-first-release)
12. [Known limitations and what's intentionally out of scope](#12-known-limitations-and-whats-intentionally-out-of-scope)
13. [File-by-file map](#13-file-by-file-map)

---

## 1. Starting point

The repository originally contained two files:

- `agentic_ops_copilot.py` (117 lines) — a single-file LangGraph prototype.
- `README.md` — a description of the *intended* system.

The prototype demonstrated the shape of an SRE incident copilot: take a ticket, gather evidence, produce a root-cause hypothesis. But it had four concrete problems, found by reading the code line by line before any rewrite:

1. **It crashed on import with no API key.** `ChatOpenAI(model="gpt-4o-mini", temperature=0)` was constructed at module scope (top-level, not inside a function). Any `import agentic_ops_copilot` — including from a test file — raised immediately if `OPENAI_API_KEY` wasn't set. This environment had no such key, so the module was, as shipped, untestable and undeployable without one.
2. **The documentation described a system the code didn't implement.** The module docstring and README both claimed a *router agent*, *parallel* evidence gathering, and *vector retrieval*. The actual code was a fixed linear chain (`triage → gather_context → synthesize`); `gather_context_node` fetched logs, metrics, and context sequentially, one `await` after another; `llm_with_tools` was bound to the model and never used; `Chroma` and `OpenAIEmbeddings` were imported and never used anywhere.
3. **Every tool was a hardcoded string.** `summarize_logs`, `get_service_metrics`, and `lookup_service_context` each returned a fixed f-string. There was no seam for anyone to point the system at a real logging/metrics backend.
4. **No packaging, config, tests, API, UI, container, or CI existed.** It was a script, not a service.

The guardrail described in the docstring — "ground the summary strictly in retrieved evidence... refuse to guess" — was real in *intent* but implemented only as prompt text handed to the model. Nothing checked that the model actually complied.

## 2. What "production ready" meant here

Before writing code, three scope questions were resolved explicitly with the requester, because "production ready" and "any company can use it" are ambiguous on their own:

| Decision | Choice | Why |
|---|---|---|
| Backend realism | Typed adapter protocol + rich deterministic mock + one real adapter per capability | Anyone can run it with zero setup (mock), and see exactly how to wire their own real system (one concrete example per protocol), without shipping untested code against live credentials that don't exist in this environment. |
| LLM providers | OpenAI + Amazon Bedrock + a deterministic offline fake | The README already promised Bedrock; a fake provider makes the *whole system* — including CI — runnable and testable with zero API keys. |
| GUI shape | FastAPI serving REST + SSE plus an embedded static SPA, one container | A separate frontend service would double the Docker/CI surface for a dashboard this size. Plain HTML/CSS/JS needs no Node build step at all. |

These three decisions shaped almost every file below.

## 3. Defects fixed and why the fixes are shaped this way

### 3.1 The import-time crash

**Fix:** `src/ops_copilot/llm.py` replaces the module-level `ChatOpenAI(...)` with `get_chat_model(settings)` — a lazy factory. Provider SDK imports (`langchain_openai`, `langchain_aws`) happen *inside* their own branch of the factory, not at module top level, so installing without the `[openai]`/`[bedrock]` extras never breaks the base import.

**Why the fake model needed a specific override, not just a `_generate` implementation:** `fake` is the *default* provider, so the entire test suite and every offline code path runs through it. `synthesize_node` calls `model.with_structured_output(Finding)`. LangChain's default `BaseChatModel.with_structured_output` is implemented on top of `bind_tools` / tool-calling — a minimal fake model that only overrides `_generate` either raises or returns an `AIMessage` with no `tool_calls`, so the default structured-output path silently produces nothing useful. `FakeChatModel` in `llm.py` therefore **explicitly overrides `with_structured_output`**, returning a `RunnableLambda` that deterministically builds a valid `Finding` (including the `insufficient_evidence` branch) directly from the evidence text in the prompt. This is the single piece of code the entire offline test suite depends on existing — it's covered by its own tests (`tests/unit/test_llm.py`) for exactly that reason.

**Regression test:** `tests/unit/test_zero_env_import.py` runs `import ops_copilot; build_graph()` in a *subprocess with a scrubbed environment* — no `OPENAI_API_KEY`, no `AWS_*`, no `OPS_*` vars. This is a direct regression test for defect #1 above.

### 3.2 Making the docs true instead of aspirational

**Router agent:** `graph.py`'s `route_node` classifies severity/category from the ticket text and decides which evidence sources are relevant (`_route_condition`). A billing/auth incident skips log and metric collection entirely — verified by `test_billing_category_skips_logs_and_metrics`.

**Real parallel fan-out, and the trap in it:** `route` fans out to up to three nodes (`fetch_logs`, `fetch_metrics`, `fetch_context`) via `add_conditional_edges` returning a list of destination names — LangGraph runs all active branches of that fan-out concurrently. The critical constraint: **each fetch node returns only its own key** (`{"logs": ...}`), never the whole state dict. The original prototype's nodes mutated and returned the entire state (`state["logs"] = ...; return state`). If a *parallel* node did that here, two concurrent branches would race to overwrite the same state keys and LangGraph raises `InvalidUpdateError`. This was hit and fixed during development — see the git history / the design note in `graph.py`'s module docstring — and is covered by `test_parallel_fanout_returns_disjoint_deltas_without_error`.

**Vector retrieval, made real:** `retrieval.py` implements two interchangeable stores behind one `RunbookStore` protocol — `ChromaRunbookStore` (real vectors, via `langchain-chroma`, built lazily so importing the module never requires the extra) and `InMemoryRunbookStore` (dependency-free keyword overlap, the default). `graph.py`'s `retrieve_runbooks_node` calls whichever is configured; `synthesize_node` includes the retrieved excerpts as evidence the model can cite.

### 3.3 The guardrail, enforced instead of requested

**Fix:** `synthesize_node` calls `model.with_structured_output(Finding)` — the model *must* return a typed object (`hypotheses`, `recommended_action`, `confidence`, `evidence_refs`, `insufficient_evidence`), not free text. `validate_node` then calls `guardrails.validate_finding`, which checks every entry in `evidence_refs` against the evidence keys *actually collected during this run* (`{"logs", "metrics", "context", "runbooks"} ∩ what's present in state`). Any fabricated reference is stripped; if nothing valid remains, the finding is downgraded to `insufficient_evidence=True, confidence="low"` rather than shipped as a confident, unsupported claim.

This is mechanical enforcement, not prompt engineering — `tests/unit/test_guardrails.py` proves a finding that cites evidence never collected gets stripped and downgraded, independent of what any LLM (real or fake) actually said.

### 3.4 Persistence and the async constraint it forced

**Why `build_graph` is `async`:** the checkpointer is `AsyncSqliteSaver` from `langgraph-checkpoint-sqlite`. Its documented factory, `AsyncSqliteSaver.from_conn_string(...)`, is an `@asynccontextmanager` — it's designed to be used as `async with AsyncSqliteSaver.from_conn_string(path) as saver:`, not called and stored as a plain object. That doesn't fit a "build once at startup, use for the app's lifetime" pattern. The fix in `graph.py`'s `_build_checkpointer` opens the `aiosqlite` connection directly (`await aiosqlite.connect(...)`) and constructs `AsyncSqliteSaver(conn)` from it, tracking the connection in a module-level `WeakKeyDictionary` keyed by the compiled graph object (not a dynamic attribute on a third-party class, which would fail type-checking) so `close_graph()` can release it cleanly on shutdown. This is why `build_graph()` — and therefore the CLI's `analyze` command and the API's lifespan handler — are `async def`.

**Why WAL mode:** early manual testing hit `sqlite3.OperationalError: database is locked` when two processes pointed at the same checkpoint file concurrently (an artifact of running multiple manual test invocations in parallel during development, not a test-suite bug — but a real risk in production under concurrent load). `PRAGMA journal_mode=WAL` is set on the connection so readers and the single writer coexist without lock contention. Tests avoid the issue structurally: `conftest.py`'s `settings_factory` points every test at its own `tmp_path`-scoped SQLite file.

**Why history is a separate table, not reconstructed from checkpoints:** `store.py`'s `RunStore` persists the API-facing `RunRecord` summary in its own small SQLite table, deliberately decoupled from the LangGraph checkpointer. Reconstructing a UI-friendly run summary from raw graph checkpoints on every history read would be more code for no benefit — the two concerns (resumable execution state vs. a queryable run history) are genuinely separate and are kept that way.

### 3.5 Async throughout, decided once, early

Graph nodes, backend adapters (`httpx.AsyncClient`), and API endpoints are all `async`. This was decided before writing the fetch nodes rather than discovered partway through, because the alternative — sync nodes with LangGraph running them in a threadpool, mixed with async HTTP calls — is a documented footgun that fails in confusing ways under load, and retrofitting it across ~25 files later would have been expensive. The SSE streaming endpoint (`api.py`) also requires `astream(..., stream_mode="updates")`, which only makes sense with async nodes.

## 4. Architecture, end to end

```
Incident (ticket_text, service_name)
        │
        ▼
    route ─────────────────────────────┐  triage severity/category;
        │                              │  decide which evidence sources
        │ (conditional fan-out)        │  are relevant
        ├──────────────┬───────────────┤
        ▼              ▼               ▼
   fetch_logs     fetch_metrics   fetch_context      (parallel; each returns
        │              │               │              only its own state key)
        └──────────────┴───────────────┘
                        │
                        ▼
              retrieve_runbooks           top-k relevant runbook excerpts
                        │
                        ▼
                  synthesize             LLM call via with_structured_output(Finding)
                        │
                        ▼
                   validate              strip evidence_refs not actually collected;
                        │                downgrade to insufficient_evidence if nothing valid remains
                        ▼
                     Finding
```

A `SqliteSaver`-backed checkpoint means a run's state survives a process restart; a separate `RunStore` table means run *history* is queryable by the API/UI without touching the graph's internal checkpoint format.

## 5. Every module, what it does and why it exists

| Module | Responsibility | Key design choice |
|---|---|---|
| `config.py` | All settings, `pydantic-settings`, `OPS_`-prefixed env vars | Every field has a default that makes the *whole system* work with zero env vars — provider `fake`, backends `mock`. This was made a hard requirement, not a nice-to-have, because it's what "works out of the box for anyone" actually means. |
| `schemas.py` | Typed contracts: `IncidentRequest`, `Triage`, `LogEvidence`, `MetricEvidence`, `ServiceContext`, `RunbookExcerpt`, `Finding`, `RunRecord` | Every boundary in the system (tool ↔ graph, graph ↔ API, API ↔ UI) passes one of these, not a dict or a string — the original prototype's tools returned raw strings, which is exactly what made the guardrail unenforceable mechanically. |
| `llm.py` | Lazy provider factory (`fake`/`openai`/`bedrock`) | See §3.1. |
| `graph.py` | The LangGraph state machine | See §3.2–3.5. |
| `guardrails.py` | Evidence-grounding enforcement | See §3.3. |
| `retrieval.py` | Runbook retrieval, real or in-memory | See §3.2. |
| `tools/base.py` | `LogsBackend`/`MetricsBackend`/`ServiceCatalog` protocols, `BackendError` | The seam described in §6. |
| `tools/mock.py` | Deterministic mock backends | Scenario is selected by a SHA-256 hash of the service name, so the *same* service name always produces the *same* evidence — reproducible demos and reproducible tests, with zero setup. Four scenarios ship: `db_pool_exhaustion`, `bad_deploy`, `dependency_outage`, `insufficient_evidence`. |
| `tools/prometheus.py`, `tools/loki.py` | Real reference adapters | One concrete real implementation per protocol, so extending to your own backend has a working example to copy, not just an abstract interface. |
| `tools/registry.py` | Config → adapter instance | The only place that needs to change to add a new backend choice. |
| `store.py` | `RunRecord` persistence for the history API | See §3.4. |
| `observability.py` | `structlog` JSON logging, Prometheus metrics, request-ID context var | Keeps logging/metrics concerns out of business logic files. |
| `api.py` | FastAPI app: REST, SSE, auth, rate limiting, health, embedded SPA | See §7 and §11. |
| `cli.py` | Typer CLI (`analyze`, `serve`, `backends`) | Preserves the original prototype's one-shot usage pattern in a supported form. |
| `web/` | The dashboard (plain HTML/CSS/JS) | No build step, no Node in the image — see the GUI decision in §2. |

## 6. The adapter seam — how to extend this

Every ops tool is a `typing.Protocol` in `tools/base.py`:

```python
class LogsBackend(Protocol):
    async def summarize(self, service_name: str, window_minutes: int) -> LogEvidence: ...


class MetricsBackend(Protocol):
    async def query(self, service_name: str) -> MetricEvidence: ...


class ServiceCatalog(Protocol):
    async def lookup(self, service_name: str) -> ServiceContext: ...
```

To point this at a real internal system: implement the relevant protocol (return the typed `*Evidence`/`*Context` model, not a string), raise `BackendError` on failure rather than letting a raw exception escape, and register the choice in `tools/registry.py`'s `get_logs_backend`/`get_metrics_backend`/`get_service_catalog`. Nothing in `graph.py`, `guardrails.py`, or `api.py` needs to change — they only ever see the typed evidence models, never the backend implementation.

LLM providers follow the identical pattern in `llm.py`'s `get_chat_model`.

## 7. The GUI

`src/ops_copilot/web/` is a self-contained SPA: `index.html`, `styles.css` (light/dark aware via `prefers-color-scheme`), and `app.js` (no framework, no build step). It's mounted directly by FastAPI's `StaticFiles` at `/`, so the whole service — API and UI — is one process, one port, one Docker image.

The submission flow calls `POST /api/v1/incidents/stream`, reads the response as an SSE stream, and renders each `node` event as a progress line and the final `completed` event as the rendered finding — so a user watches the graph's route → fetch → synthesize → validate steps happen live, not just a spinner. Run history is fetched from `GET /api/v1/incidents` and re-fetched after each new run.

## 8. Observability

`observability.py` configures `structlog` to emit JSON logs with a per-request ID (via a `contextvars.ContextVar`, set by API middleware) and defines three Prometheus metrics: `ops_copilot_requests_total{status}`, `ops_copilot_request_duration_seconds`, and `ops_copilot_node_duration_seconds{node}`. `/metrics` on the API exposes them in Prometheus exposition format; `/readyz` reports the resolved provider/backend configuration so a deploy can be verified without reading logs.

## 9. Docker and CI

The `Dockerfile` is a two-stage build: a `builder` stage installs the package into a venv (so build tooling never ships in the runtime image), and a `runtime` stage copies only that venv, creates and switches to a non-root `app` user, and declares a container `HEALTHCHECK` against `/healthz`. `compose.yaml` adds a named volume for the SQLite data directory and an opt-in `real-backends` profile that brings up Prometheus and Loki containers to demo the real adapters against.

`.github/workflows/ci.yml` runs lint (`ruff check`, `ruff format --check`), `mypy`, and the full `pytest` suite across Python 3.10/3.11/3.12, then builds the Docker image as a separate job gated on tests passing.

## 10. Testing strategy and what was actually verified

The suite is intentionally structured around the defects it exists to catch, not just "cover the code":

- **`tests/unit/test_zero_env_import.py`** — the direct regression test for the original crash (§3.1).
- **`tests/unit/test_llm.py`** — proves the fake model's `with_structured_output` override actually returns a valid `Finding` for both the grounded and insufficient-evidence cases, and that the model is cached rather than rebuilt per call. This is the test that proves the rest of the offline suite is even meaningful.
- **`tests/unit/test_guardrails.py`** — fabricated `evidence_refs` are stripped and the finding downgraded, independent of what any model said.
- **`tests/unit/test_mock_backends.py`**, **`test_retrieval.py`**, **`test_config.py`** — determinism and zero-env defaults.
- **`tests/unit/test_real_adapters.py`** — Prometheus/Loki request/response parsing against `httpx` mock transports, including the `BackendError` path on a simulated connection failure. No real network access.
- **`tests/integration/test_graph.py`** — full graph runs across the grounded, insufficient-evidence, and billing (router-skips-evidence) scenarios; a dedicated regression test for the parallel-fan-out `InvalidUpdateError` trap (§3.2); and (added in the second hardening pass, §11) a simulated `BackendError` proving a live backend outage degrades gracefully instead of crashing the run.
- **`tests/integration/test_api.py`** — every endpoint via `httpx.ASGITransport` + `asgi-lifespan`, SSE event parsing, auth enforcement, and (added in the second pass) rate-limit enforcement and its exemption for `/healthz`/`/readyz`.

**What this environment could verify, and what it could not:** every command below was actually run, not just written:

- `pytest --cov=ops_copilot` — 39 tests passing, ~86% line coverage.
- `ruff check .` / `ruff format --check .` — clean.
- `mypy src/` — clean, no errors.
- The CLI (`ops-copilot analyze`, `ops-copilot backends`) — run directly, output inspected.
- The API server (`ops-copilot serve`) — started, and `/healthz`, `/readyz`, `/metrics`, `/docs`, `POST /api/v1/incidents`, `POST /api/v1/incidents/stream`, `GET /api/v1/incidents` were all exercised with real HTTP requests against a running process.
- The dashboard — screenshotted via headless Chrome against the running server (see `docs/screenshots/`).
- `docker build` and `docker run` — the image was actually built and run in this environment; `/healthz` and a real incident POST were verified against the running container, and `docker exec ... whoami` confirmed the process runs as the non-root `app` user, not root.

**What could not be verified, and is not claimed to be:** there is no `OPENAI_API_KEY` or AWS credentials configured in this environment. The real `openai` and `bedrock` branches of `llm.py`, and genuinely live (non-mocked) calls to a real Prometheus or Loki instance, were never exercised end to end against a live service — only their request-construction and response-parsing logic was, via `httpx` mock transports. Anything described as "tested" or "verified" in this document and the README refers to the offline suite (fake model + mock backends + mocked HTTP) unless stated otherwise.

## 11. Second hardening pass — what was added after the first release

After the initial rebuild, a second review focused specifically on gaps between what the config/docs *claimed* and what the code actually *did* — the same category of defect the original prototype had, just smaller in scope this time.

**Backend failures no longer crash the whole run.** `tools/base.py`'s `BackendError` was defined and raised by the real Prometheus/Loki adapters from the start, but nothing in `graph.py` caught it — a real backend timeout would propagate uncaught through the fetch node and fail the entire incident analysis, taking down evidence that *was* successfully collected along with it. `fetch_logs_node`, `fetch_metrics_node`, and `fetch_context_node` now each catch `BackendError`, log it via `structlog` with the service name and backend, and return `{"<key>": None, "degraded": ["<key>"]}` instead of letting the exception escape. `OpsState.degraded` is `Annotated[list[str], operator.add]` — a reducer, unlike every other state key in this graph — because multiple concurrent fetch nodes can each append to it in the same parallel superstep; every other key here is deliberately disjoint per node and needs no reducer, but this one genuinely can be written by more than one branch. `_format_evidence` distinguishes *"none — not collected for this category"* (the router decided it wasn't relevant) from *"unavailable — backend error while fetching this evidence"* (we tried and failed) — the model must not treat a real outage as a clean absence of evidence, and an on-call engineer reading the finding needs to know which one happened. `validate_node`'s existing evidence-collected check (`{k for k in (...) if state.get(k)}`) already treats a `None` value as not-collected correctly, with no change needed there — a degraded source is automatically excluded from valid `evidence_refs` by logic that already existed. `RunRecord.degraded` surfaces this in the API/UI. Covered by `test_backend_error_degrades_gracefully_instead_of_crashing_the_run`.

**Rate limiting, actually enforced.** `Settings.rate_limit_per_minute` existed from the first release but nothing read it — dead configuration that implied a protection the service didn't have. `api.py` now has an in-process sliding-window limiter, keyed by client IP, as ASGI middleware. It's explicitly documented (README, `.env.example`) as per-worker rather than global — a shared store like Redis would be disproportionate to this project's size, and pretending otherwise would be a worse lie than the original dead config. `/healthz` and `/readyz` are exempted so liveness/readiness probes are never throttled under load — a self-inflicted outage otherwise. Returns `429` with `Retry-After: 60`. Covered by `test_rate_limit_returns_429_once_exceeded` and `test_rate_limit_exempts_health_probes`.

**The auth/dashboard coherence bug.** Setting `OPS_API_KEY` requires `X-API-Key` on every `/api/v1/*` call — but the dashboard's `app.js` never sent it, so enabling the one security feature silently broke the other shipped feature (the GUI). `app.js` now has an `apiFetch` wrapper: it attaches a key from `localStorage` if one is stored, and on a `401` response prompts once for the key and stores it for subsequent requests. This keeps auth meaningful (the key is never baked into the served JS) while making the two features actually compose. The static SPA routes themselves remain unauthenticated by design — `OPS_API_KEY` protects the API, not the page shell.

**`LICENSE`.** Added to match the `license = { text = "MIT" }` field already declared in `pyproject.toml` — the field existed without a corresponding file.

Deliberately **not** added in this pass, after review: security-header middleware, request-size limits, and retry/backoff (e.g. via `tenacity`) on backend calls. Each would add surface area and its own tests for a defect this project doesn't actually have evidence of — the three fixes above were chosen because each closed a real gap between a claim already made (in config, in docs, or by a feature's existence) and what the code did, which is the same standard the original rebuild was held to.

## 12. Known limitations and what's intentionally out of scope

- **Real LLM/backend paths are structurally correct but not live-verified** — see §10's honest-limits paragraph. This is an environment constraint (no credentials), not a code gap; the code paths exist and are exercised via mocks.
- **Rate limiting and run history are per-process.** Multiple uvicorn workers or horizontally scaled replicas each keep independent rate-limit counters and (for history) independent SQLite files unless `OPS_CHECKPOINT_DB_PATH` points at shared storage. Acceptable for the single-process deployment this project targets; a multi-replica production deployment would need a shared store (Redis for rate limiting, a networked database for history) — genuinely out of scope for this project's size, not an oversight.
- **The triage classifier is deterministic keyword matching**, not an ML model or an LLM call (`graph.py`'s `_triage_ticket`). This is intentional: it keeps the router's *decisions* (which evidence to fetch) reproducible and testable independent of any LLM's non-determinism. A production deployment wanting smarter triage would swap this function's internals without touching anything else in the graph.
- **No authentication beyond a single shared API key.** There's no per-user identity, no OAuth, no RBAC. Fine for an internal on-call tool behind a VPN/internal network; not intended as a public-facing multi-tenant service without a proper auth layer in front of it.

## 13. File-by-file map

```
Agentic-ops-copilot/
├── agentic_ops_copilot.py       deprecated shim — re-exports the graph so `python agentic_ops_copilot.py` still works
├── pyproject.toml                packaging, dependencies, extras, tool config (ruff/mypy/pytest)
├── Dockerfile                    multi-stage, non-root runtime
├── compose.yaml                  local orchestration + optional real-backends profile
├── Makefile                      install/test/lint/typecheck/docker targets
├── .env.example                  every setting, commented, placeholders only
├── .github/workflows/ci.yml      lint + typecheck + test matrix, then a Docker build job
├── LICENSE                       MIT
├── runbooks/                     sample runbooks indexed by retrieval.py
├── docs/
│   ├── PROJECT_DOCUMENTATION.md  this file
│   └── screenshots/               dashboard + API docs screenshots used in the README
├── src/ops_copilot/
│   ├── config.py, schemas.py, llm.py, graph.py, guardrails.py, retrieval.py
│   ├── tools/                    base.py (protocols), mock.py, prometheus.py, loki.py, registry.py
│   ├── store.py, observability.py, api.py, cli.py
│   └── web/                      index.html, styles.css, app.js
└── tests/
    ├── conftest.py                zero-env defaults + settings_factory fixture
    ├── unit/                      llm, guardrails, mock backends, config, retrieval, real adapters, zero-env import
    └── integration/               full graph runs, API endpoints
```

See the [README](../README.md) for installation, configuration, and usage; this document is the record of *why* the code looks the way it does.
