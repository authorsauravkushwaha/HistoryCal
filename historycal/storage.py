"""
storage.py
==========

Saves the user's own birthdays/anniversaries/events to a plain JSON file
next to the program, so nothing is lost between runs and no database
server is needed.

Design choices worth noticing (this is the "make it stable" part):

* Writes are *atomic*: we write to a temporary file and then rename it
  over the real file. On every mainstream OS, rename is a single atomic
  operation, so a crash or power-cut mid-save can never leave you with a
  half-written, corrupted events file.
* If the file on disk turns out to be corrupted anyway (edited by hand,
  copied badly, etc.) we don't crash the app - we back up the bad file
  and start with an empty store, and tell the caller what happened.
* A birthday is stored with `year=None` and `recurring=True`, meaning
  "match this month/day every year, forever" - which is what lets a
  birthday show up correctly whether you're looking at last year or the
  year 5026.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, asdict, field
from typing import Optional


CATEGORIES = ["birthday", "anniversary", "personal", "historical", "other"]


@dataclass
class Event:
    id: str
    title: str
    month: int
    day: int
    year: Optional[int] = None   # None => recurs every year
    recurring: bool = True
    category: str = "other"
    notes: str = ""

    def matches(self, year: int, month: int, day: int) -> bool:
        if self.month != month or self.day != day:
            return False
        if self.recurring:
            return True
        return self.year == year


class EventStore:
    def __init__(self, path: str):
        self.path = path
        self._events: dict[str, Event] = {}
        self.last_load_warning: Optional[str] = None
        self.load()

    # -- persistence ------------------------------------------------

    def load(self) -> None:
        self.last_load_warning = None
        if not os.path.exists(self.path):
            self._events = {}
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            events = {}
            for item in raw.get("events", []):
                ev = Event(
                    id=item["id"],
                    title=item["title"],
                    month=int(item["month"]),
                    day=int(item["day"]),
                    year=item.get("year"),
                    recurring=bool(item.get("recurring", True)),
                    category=item.get("category", "other"),
                    notes=item.get("notes", ""),
                )
                events[ev.id] = ev
            self._events = events
        except (json.JSONDecodeError, KeyError, ValueError, OSError) as exc:
            backup_path = self.path + ".corrupted.bak"
            try:
                shutil.copyfile(self.path, backup_path)
            except OSError:
                backup_path = None
            self._events = {}
            self.last_load_warning = (
                f"Could not read {self.path} ({exc}). Starting with an "
                f"empty calendar." +
                (f" A copy of the bad file was saved to {backup_path}."
                 if backup_path else "")
            )

    def save(self) -> None:
        payload = {"events": [asdict(e) for e in self._events.values()]}
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.path)   # atomic on POSIX and Windows

    # -- CRUD ---------------------------------------------------------

    def add(self, title: str, month: int, day: int, year: Optional[int] = None,
            recurring: bool = True, category: str = "other", notes: str = "") -> Event:
        ev = Event(id=str(uuid.uuid4()), title=title, month=month, day=day,
                   year=year, recurring=recurring, category=category, notes=notes)
        self._events[ev.id] = ev
        self.save()
        return ev

    def remove(self, event_id: str) -> None:
        self._events.pop(event_id, None)
        self.save()

    def update(self, event_id: str, **fields) -> Optional[Event]:
        ev = self._events.get(event_id)
        if ev is None:
            return None
        for k, v in fields.items():
            setattr(ev, k, v)
        self.save()
        return ev

    def events_for(self, year: int, month: int, day: int) -> list[Event]:
        return [e for e in self._events.values() if e.matches(year, month, day)]

    def all_events(self) -> list[Event]:
        return sorted(self._events.values(), key=lambda e: (e.month, e.day))

    def __len__(self) -> int:
        return len(self._events)
