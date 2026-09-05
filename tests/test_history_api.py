"""
These tests never touch the real network (this sandbox's egress rules
block Wikipedia anyway, and tests shouldn't depend on the internet being
up regardless). Instead we:
  - feed hand-built JSON, shaped exactly like Wikipedia's real response,
    straight into the parser
  - monkeypatch urllib.request.urlopen to simulate network success/failure
"""
import os
import sys
import tempfile
import shutil
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from historycal import history_api as hapi

# A trimmed, realistic sample shaped exactly like the real
# /api/rest_v1/feed/onthisday/events/09/05 response from Wikipedia.
SAMPLE_RESPONSE = {
    "events": [
        {
            "text": "The Battle of Lake Erie is fought during the War of 1812.",
            "year": 1813,
            "pages": [{"title": "Battle of Lake Erie"}],
        },
        {
            "text": "Mother Teresa, Albanian-Indian nun and missionary, dies.",
            "year": 1997,
            "pages": [{"title": "Mother Teresa"}],
        },
        {
            "text": "The Reign of Terror begins in France.",
            "year": 1793,
            "pages": [{"title": "Reign of Terror"}],
        },
    ]
}


def with_temp_dir(fn):
    def wrapper():
        d = tempfile.mkdtemp()
        try:
            fn(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
    wrapper.__name__ = fn.__name__
    return wrapper


def test_parse_events_sorts_newest_first():
    events = hapi._parse_events(SAMPLE_RESPONSE)
    years = [e.year for e in events]
    assert years == sorted(years, reverse=True)
    assert years[0] == 1997
    assert years[-1] == 1793


def test_parse_events_skips_malformed_entries():
    broken = {"events": [{"text": "no year here"}, {"year": 1900}]}
    events = hapi._parse_events(broken)
    assert events == []


def test_battle_filter_keeps_only_war_related():
    events = hapi._parse_events(SAMPLE_RESPONSE)
    battles = hapi.filter_battles(events)
    texts = [e.text for e in battles]
    assert any("Battle of Lake Erie" in t for t in texts)
    assert not any("Mother Teresa" in t for t in texts)


@with_temp_dir
def test_cache_round_trip(tmpdir):
    events = hapi._parse_events(SAMPLE_RESPONSE)
    hapi._save_cache(tmpdir, 9, 5, events)
    loaded = hapi._load_cache(tmpdir, 9, 5)
    assert loaded is not None
    assert [e.text for e in loaded] == [e.text for e in events]
    assert [e.year for e in loaded] == [e.year for e in events]


@with_temp_dir
def test_fetch_uses_cache_without_network(tmpdir, monkeypatch=None):
    events = hapi._parse_events(SAMPLE_RESPONSE)
    hapi._save_cache(tmpdir, 9, 5, events)

    def boom(*a, **kw):
        raise AssertionError("network should NOT be called when cache exists")

    import urllib.request
    original = urllib.request.urlopen
    urllib.request.urlopen = boom
    try:
        result = hapi.fetch_on_this_day(9, 5, tmpdir)
    finally:
        urllib.request.urlopen = original

    assert result.ok
    assert result.source == "cache"
    assert len(result.events) == 3


@with_temp_dir
def test_fetch_falls_back_to_stale_cache_on_network_failure(tmpdir):
    events = hapi._parse_events(SAMPLE_RESPONSE)
    hapi._save_cache(tmpdir, 9, 5, events)

    def fail(*a, **kw):
        raise urllib.error.URLError("simulated network down")

    import urllib.request
    original = urllib.request.urlopen
    urllib.request.urlopen = fail
    try:
        result = hapi.fetch_on_this_day(9, 5, tmpdir, force_refresh=True)
    finally:
        urllib.request.urlopen = original

    assert not result.ok                 # error is set...
    assert len(result.events) == 3       # ...but we still got the stale data
    assert "Offline" in result.error


@with_temp_dir
def test_fetch_with_no_network_and_no_cache_fails_gracefully(tmpdir):
    def fail(*a, **kw):
        raise urllib.error.URLError("simulated network down")

    import urllib.request
    original = urllib.request.urlopen
    urllib.request.urlopen = fail
    try:
        result = hapi.fetch_on_this_day(1, 1, tmpdir)  # never cached
    finally:
        urllib.request.urlopen = original

    assert not result.ok
    assert result.events == []
    assert result.source == "none"


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"\nAll {len(tests)} history_api tests passed.")
