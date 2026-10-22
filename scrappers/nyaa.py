"""
scrappers/nyaa.py — Unified Nyaa Scraper
Delegates to providers.torrents.nyaa.NyaaProvider to eliminate duplicate scraper logic,
unify circuit-breaker health tracking, and reuse HTTP connection pooling.
"""
from typing import Optional
from providers.torrents.nyaa import NyaaProvider

# Alias for backwards compatibility with tests and callers
NyaaScraper = NyaaProvider

_nyaa_provider_instance: Optional[NyaaProvider] = None


def get_nyaa_scraper() -> NyaaProvider:
    global _nyaa_provider_instance
    if _nyaa_provider_instance is None:
        _nyaa_provider_instance = NyaaProvider()
    return _nyaa_provider_instance
