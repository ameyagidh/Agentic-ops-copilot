"""Runbook retrieval.

Indexes the markdown files in ``runbooks/`` and returns the top-k most
relevant excerpts for a given query (typically the incident category +
ticket text). Two implementations:

- ``ChromaRunbookStore``: real vector retrieval via ``langchain-chroma`` +
  OpenAI embeddings — used when the ``retrieval`` extra is installed and an
  embeddings provider is configured.
- ``InMemoryRunbookStore``: a dependency-free keyword-overlap store used
  otherwise, so retrieval still works fully offline with zero extras.

Both implement the same ``retrieve(query, k)`` interface so ``graph.py``
doesn't need to know which one is active.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from ops_copilot.config import Settings
from ops_copilot.schemas import RunbookExcerpt

_WORD_RE = re.compile(r"[a-zA-Z]{3,}")


class RunbookStore(Protocol):
    async def retrieve(self, query: str, k: int = 3) -> list[RunbookExcerpt]: ...


def _load_runbooks(runbooks_dir: str) -> list[tuple[str, str]]:
    """Returns list of (title, full_text) for each runbook file."""
    directory = Path(runbooks_dir)
    if not directory.is_dir():
        return []
    docs = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        first_line = text.strip().splitlines()[0] if text.strip() else path.stem
        title = first_line.lstrip("#").strip() or path.stem
        docs.append((title, text))
    return docs


class InMemoryRunbookStore:
    """Zero-dependency keyword-overlap retrieval. Deterministic and fast —
    good enough for short runbook documents and keeps offline mode fully
    functional without a vector DB or embeddings API.
    """

    def __init__(self, runbooks_dir: str) -> None:
        self._docs = _load_runbooks(runbooks_dir)

    async def retrieve(self, query: str, k: int = 3) -> list[RunbookExcerpt]:
        query_words = set(_WORD_RE.findall(query.lower()))
        if not query_words or not self._docs:
            return []

        scored = []
        for title, text in self._docs:
            doc_words = _WORD_RE.findall(text.lower())
            overlap = sum(1 for w in doc_words if w in query_words)
            if overlap:
                scored.append((overlap, title, text))

        scored.sort(key=lambda t: t[0], reverse=True)
        results = []
        for _, title, text in scored[:k]:
            snippet = " ".join(text.split())[:400]
            results.append(RunbookExcerpt(title=title, snippet=snippet, source=f"runbooks/{title}"))
        return results


class ChromaRunbookStore:
    """Real vector retrieval, built lazily so importing this module never
    requires the ``retrieval`` extra or network access.
    """

    def __init__(self, runbooks_dir: str, vector_store_dir: str) -> None:
        from langchain_chroma import Chroma
        from langchain_core.documents import Document
        from langchain_openai import OpenAIEmbeddings

        docs = [Document(page_content=text, metadata={"title": title}) for title, text in _load_runbooks(runbooks_dir)]
        embeddings = OpenAIEmbeddings()
        if docs:
            self._store = Chroma.from_documents(docs, embedding=embeddings, persist_directory=vector_store_dir)
        else:
            self._store = Chroma(embedding_function=embeddings, persist_directory=vector_store_dir)

    async def retrieve(self, query: str, k: int = 3) -> list[RunbookExcerpt]:
        results = self._store.similarity_search(query, k=k)
        return [
            RunbookExcerpt(
                title=doc.metadata.get("title", "runbook"),
                snippet=doc.page_content[:400],
                source=f"runbooks/{doc.metadata.get('title', 'runbook')}",
            )
            for doc in results
        ]


def get_runbook_store(settings: Settings) -> RunbookStore:
    if settings.retrieval_enabled and settings.embeddings_provider == "openai":
        try:
            return ChromaRunbookStore(settings.runbooks_dir, settings.vector_store_dir)
        except ImportError:
            # `retrieval` extra not installed — degrade to offline store
            # rather than failing the whole run.
            return InMemoryRunbookStore(settings.runbooks_dir)
    return InMemoryRunbookStore(settings.runbooks_dir)
