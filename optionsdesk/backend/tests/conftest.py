"""Shared pytest fixtures.

The Alpha Vantage client keeps a short-TTL module-level response cache (so the
desk's mark + greeks calls share one fetch instead of hammering the API). That
cache must not leak between tests — each test mocks its own httpx payloads, so
a stale cached response from a prior test would corrupt it. Clear it around
every test.
"""
import pytest


@pytest.fixture(autouse=True)
def _clear_av_cache():
    from optdesk.live import alpha_vantage as av
    av._cache.clear()
    yield
    av._cache.clear()
