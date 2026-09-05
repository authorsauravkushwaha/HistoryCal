import os
import sys
import json
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from historycal.storage import EventStore


def with_temp_dir(fn):
    def wrapper():
        d = tempfile.mkdtemp()
        try:
            fn(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
    wrapper.__name__ = fn.__name__
    return wrapper


@with_temp_dir
def test_add_and_retrieve_recurring_birthday(tmpdir):
    path = os.path.join(tmpdir, "events.json")
    store = EventStore(path)
    store.add("Mom's Birthday", month=9, day=15, category="birthday")

    # a recurring birthday should show up in *any* year, incl. far future/past
    for year in (2020, 2026, 5026, -500):
        matches = store.events_for(year, 9, 15)
        assert len(matches) == 1
        assert matches[0].title == "Mom's Birthday"

    assert store.events_for(2026, 9, 16) == []


@with_temp_dir
def test_one_time_event_only_matches_its_year(tmpdir):
    path = os.path.join(tmpdir, "events.json")
    store = EventStore(path)
    store.add("Graduation Trip", month=6, day=1, year=2028, recurring=False)

    assert len(store.events_for(2028, 6, 1)) == 1
    assert len(store.events_for(2029, 6, 1)) == 0


@with_temp_dir
def test_persistence_across_reloads(tmpdir):
    path = os.path.join(tmpdir, "events.json")
    store1 = EventStore(path)
    ev = store1.add("Independence Day", month=8, day=15, category="historical")

    store2 = EventStore(path)   # simulate restarting the app
    matches = store2.events_for(2026, 8, 15)
    assert len(matches) == 1
    assert matches[0].id == ev.id


@with_temp_dir
def test_update_and_remove(tmpdir):
    path = os.path.join(tmpdir, "events.json")
    store = EventStore(path)
    ev = store.add("Placeholder", month=1, day=1)

    store.update(ev.id, title="New Year's Day", category="other")
    assert store.events_for(2026, 1, 1)[0].title == "New Year's Day"

    store.remove(ev.id)
    assert store.events_for(2026, 1, 1) == []
    assert len(store) == 0


@with_temp_dir
def test_atomic_write_leaves_no_tmp_file_behind(tmpdir):
    path = os.path.join(tmpdir, "events.json")
    store = EventStore(path)
    store.add("Test", month=3, day=3)
    assert os.path.exists(path)
    assert not os.path.exists(path + ".tmp")


@with_temp_dir
def test_corrupted_file_recovers_gracefully(tmpdir):
    path = os.path.join(tmpdir, "events.json")
    with open(path, "w") as f:
        f.write("{ this is not valid json ]")

    store = EventStore(path)   # must not raise
    assert len(store) == 0
    assert store.last_load_warning is not None
    assert os.path.exists(path + ".corrupted.bak")

    # app should still work perfectly after recovering
    store.add("Fresh Start", month=1, day=1)
    assert len(store) == 1


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"\nAll {len(tests)} storage tests passed.")
