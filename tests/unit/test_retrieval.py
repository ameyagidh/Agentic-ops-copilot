import pytest

from ops_copilot.retrieval import InMemoryRunbookStore, get_runbook_store


@pytest.mark.asyncio
async def test_in_memory_store_retrieves_relevant_runbook():
    store = InMemoryRunbookStore(runbooks_dir="runbooks")
    results = await store.retrieve("database connection pool exhausted errors", k=3)
    assert results
    assert any("pool" in r.title.lower() for r in results)


@pytest.mark.asyncio
async def test_in_memory_store_empty_query_returns_nothing():
    store = InMemoryRunbookStore(runbooks_dir="runbooks")
    assert await store.retrieve("", k=3) == []


@pytest.mark.asyncio
async def test_missing_runbooks_dir_is_handled_gracefully():
    store = InMemoryRunbookStore(runbooks_dir="does-not-exist")
    assert await store.retrieve("deploy rollback", k=3) == []


def test_get_runbook_store_defaults_to_in_memory(settings_factory):
    settings = settings_factory()
    store = get_runbook_store(settings)
    assert isinstance(store, InMemoryRunbookStore)
