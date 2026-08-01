import pytest

from ops_copilot.tools.mock import MockLogsBackend, MockMetricsBackend, MockServiceCatalog


@pytest.mark.asyncio
async def test_logs_backend_is_deterministic():
    backend = MockLogsBackend()
    first = await backend.summarize("checkout-api", window_minutes=30)
    second = await backend.summarize("checkout-api", window_minutes=30)
    assert first == second
    assert first.service_name == "checkout-api"
    assert first.window_minutes == 30


@pytest.mark.asyncio
async def test_metrics_backend_is_deterministic():
    backend = MockMetricsBackend()
    first = await backend.query("checkout-api")
    second = await backend.query("checkout-api")
    assert first == second
    assert first.p99_latency_ms > 0


@pytest.mark.asyncio
async def test_service_catalog_is_deterministic():
    catalog = MockServiceCatalog()
    first = await catalog.lookup("checkout-api")
    second = await catalog.lookup("checkout-api")
    assert first == second
    assert first.owner_team
    assert first.dependencies


@pytest.mark.asyncio
async def test_different_services_can_yield_different_scenarios():
    backend = MockLogsBackend()
    names = ["a", "b", "c", "d", "e"]
    results = {name: (await backend.summarize(name, 30)).summary for name in names}
    assert len(set(results.values())) > 1
