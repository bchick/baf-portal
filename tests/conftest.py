"""Shared fixtures.

Tests are network-free: HTTP goes through pipeline.common.fetch, which reads
data/cache/. `offline` makes any cache miss raise NoNetwork, and tests that
need cached API data skip instead of silently going online. Data-contract
tests read the last `pixi run build-data` output and skip if it is absent.
"""
from __future__ import annotations

import json
from collections import Counter

import pytest

from pipeline import common


class NoNetwork(RuntimeError):
    pass


@pytest.fixture
def offline(monkeypatch):
    def refuse(*a, **k):
        raise NoNetwork("network access attempted in an offline test")
    monkeypatch.setattr(common._session, "request", refuse)


def cached_or_skip(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except NoNetwork:
        pytest.skip("needs cached API data (run `pixi run build-data` once)")


@pytest.fixture
def stats():
    return Counter()


@pytest.fixture(scope="session")
def built():
    latest = common.SITE_DATA / "latest.json"
    if not latest.exists():
        pytest.skip("no built data (run `pixi run build-data`)")
    info = json.loads(latest.read_text())
    root = common.SITE_DATA / info["path"]
    odbl = common.SITE_DATA / info["odbl"]

    class Built:
        def gene(self, g): return json.loads((root / f"{g}.json").read_text())
        def refs(self, g=None): return json.loads((root / (f"{g}.refs.json" if g else "refs.json")).read_text())
        def tcga(self, g): return json.loads((odbl / f"{g}.tcga.json").read_text())
        def manifest(self): return json.loads((root / "manifest.json").read_text())
        path = root

    return Built()
