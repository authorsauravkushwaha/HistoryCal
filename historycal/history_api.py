"""
history_api.py
===============

Pulls "on this day in history" events for a given month/day from
Wikipedia's free, public, key-free REST API:

    https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{MM}/{DD}

Two important design points:

1. The endpoint is keyed by MONTH and DAY only, not by year. That is
   exactly what this project needs: whatever date the user has navigated
   to - 2026, 1926, or the year 30,000 - we always ask "what happened on
   this calendar day across history?" and Wikipedia's dataset (spanning
   thousands of years of recorded history, many entries about wars,
   battles, invasions, treaties and empires from countries all over the
   world) answers that question regardless of which year the request
   came from.

2. Every response is cached to disk forever (a historical fact about
   March 15th doesn't change tomorrow), which makes the app fast after
   the first visit to a given day and lets it keep working offline. If
   the network is unavailable and no cache exists, we fail politely and
   say so instead of crashing.

No third-party packages are used - only Python's standard library
(`urllib`, `json`), so this keeps the whole project runnable with a
plain `python main.py`, no `pip install` required.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict


API_TEMPLATE = "https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{month:02d}/{day:02d}"

# Wikipedia's API etiquette asks for a descriptive User-Agent identifying
# the application and (ideally) a contact URL - please swap in your own
# GitHub repo link if you fork this project.
USER_AGENT = ("HistoryCal/1.0 (student project; "
              "https://github.com/ ; contact via GitHub) Python-urllib")

BATTLE_KEYWORDS = [
    "battle", "war", "invasion", "siege", "revolt", "rebellion",
    "uprising", "conquest", "empire", "army", "military", "treaty",
    "coup", "massacre", "insurrection", "mutiny", "campaign",
    "offensive", "troops", "regiment", "front", "annexation",
]


@dataclass
class HistoryEvent:
    year: int
    text: str
    pages: list

    def is_battle_related(self) -> bool:
        lowered = self.text.lower()
        return any(kw in lowered for kw in BATTLE_KEYWORDS)


@dataclass
class HistoryResult:
    month: int
    day: int
    events: list       # list[HistoryEvent], newest year first
    source: str         # "network", "cache", or "none"
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _cache_path(cache_dir: str, month: int, day: int) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{month:02d}-{day:02d}.json")


def _load_cache(cache_dir: str, month: int, day: int):
    path = _cache_path(cache_dir, month, day)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [HistoryEvent(**e) for e in raw["events"]]
    except (json.JSONDecodeError, KeyError, OSError, TypeError):
        return None


def _save_cache(cache_dir: str, month: int, day: int, events: list) -> None:
    path = _cache_path(cache_dir, month, day)
    tmp = path + ".tmp"
    payload = {"events": [asdict(e) for e in events],
               "cached_at_unixtime": time.time()}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)


def _parse_events(raw_json: dict) -> list:
    events = []
    for item in raw_json.get("events", []):
        year = item.get("year")
        text = item.get("text")
        if year is None or not text:
            continue
        pages = [p.get("title", "") for p in item.get("pages", []) if p.get("title")]
        events.append(HistoryEvent(year=int(year), text=text, pages=pages))
    events.sort(key=lambda e: e.year, reverse=True)   # most recent first
    return events


def fetch_on_this_day(month: int, day: int, cache_dir: str,
                       timeout: float = 6.0, force_refresh: bool = False) -> HistoryResult:
    """Get historical events for a given month/day, using the on-disk
    cache whenever possible and only hitting the network when needed.
    Never raises - all failure modes come back as a HistoryResult with
    `error` set, so the UI can show a friendly message instead of
    crashing on a bad connection.
    """
    if not force_refresh:
        cached = _load_cache(cache_dir, month, day)
        if cached is not None:
            return HistoryResult(month=month, day=day, events=cached, source="cache")

    url = API_TEMPLATE.format(month=month, day=day)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_json = json.loads(response.read().decode("utf-8"))
        events = _parse_events(raw_json)
        _save_cache(cache_dir, month, day, events)
        return HistoryResult(month=month, day=day, events=events, source="network")
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
        # Network failed - fall back to a stale cache if we happen to
        # have one (better an old answer than none), otherwise give up
        # gracefully.
        stale = _load_cache(cache_dir, month, day)
        if stale is not None:
            return HistoryResult(month=month, day=day, events=stale, source="cache",
                                  error=f"Offline - showing cached data ({exc})")
        return HistoryResult(month=month, day=day, events=[], source="none",
                              error=f"Could not reach Wikipedia and no cached "
                                    f"data is available ({exc})")


def filter_battles(events: list) -> list:
    return [e for e in events if e.is_battle_related()]
