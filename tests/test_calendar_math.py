"""
Cross-checks our hand-written proleptic-Gregorian math against Python's
built-in `datetime` module (which is trusted, but limited to years 1-9999),
then separately checks that the same functions stay internally consistent
far outside that range (negative years, huge future years) where `datetime`
can't help us verify anymore.
"""
import datetime
import random
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from historycal import calendar_math as cm


def test_epoch_day_matches_datetime_toordinal():
    # datetime's own ordinal (day 1 = 0001-01-01) differs from ours
    # (day 0 = 1970-01-01) by a constant offset. If our math is right,
    # that offset should be *exactly the same* for every date we try.
    offset = None
    d = datetime.date(1, 1, 1)
    one_day = datetime.timedelta(days=1)
    # sample every ~37 days across the full datetime range to keep the
    # test fast while still covering thousands of dates, incl. leap years
    checked = 0
    while True:
        ours = cm.to_epoch_day(d.year, d.month, d.day)
        theirs = d.toordinal()
        diff = ours - theirs
        if offset is None:
            offset = diff
        assert diff == offset, f"mismatch at {d}: ours={ours} theirs={theirs}"
        checked += 1
        if d.toordinal() > datetime.date(9999, 12, 31).toordinal() - 37:
            break
        d += one_day * 37
    assert checked > 90
    print(f"epoch-day offset vs datetime.toordinal(): {offset} (checked {checked} dates)")


def test_from_epoch_day_is_inverse_matches_datetime():
    rng = random.Random(42)
    for _ in range(500):
        y = rng.randint(1, 9999)
        m = rng.randint(1, 12)
        d = rng.randint(1, cm.days_in_month(y, m))
        epoch = cm.to_epoch_day(y, m, d)
        y2, m2, d2 = cm.from_epoch_day(epoch)
        assert (y, m, d) == (y2, m2, d2)
        # cross check the actual date matches datetime's idea of the same day
        py_date = datetime.date(y, m, d)
        assert cm.to_epoch_day(y, m, d) - py_date.toordinal() == \
               cm.to_epoch_day(1970, 1, 1) - datetime.date(1970, 1, 1).toordinal()


def test_weekday_matches_datetime():
    rng = random.Random(7)
    for _ in range(500):
        y = rng.randint(1, 9999)
        m = rng.randint(1, 12)
        d = rng.randint(1, cm.days_in_month(y, m))
        py_weekday_mon0 = datetime.date(y, m, d).weekday()   # 0=Mon..6=Sun
        py_weekday_sun0 = (py_weekday_mon0 + 1) % 7           # 0=Sun..6=Sat
        assert cm.weekday_index(y, m, d) == py_weekday_sun0


def test_round_trip_survives_far_future_and_deep_past():
    for y in (-1_000_000, -12000, -1, 0, 1, 2026, 50000, 999_999_999):
        for m in (1, 2, 12):
            d = cm.days_in_month(y, m)  # last day of month, exercises leap logic too
            epoch = cm.to_epoch_day(y, m, d)
            assert cm.from_epoch_day(epoch) == (y, m, d)


def test_weekday_is_periodic_every_400_years():
    # The Gregorian calendar repeats its weekday pattern every 400 years
    # (that's the whole point of the 400-year "era" in the algorithm).
    for y in (2026, -8000, 123456):
        assert cm.weekday_index(y, 3, 15) == cm.weekday_index(y + 400, 3, 15)
        assert cm.weekday_index(y, 3, 15) == cm.weekday_index(y - 400, 3, 15)


def test_leap_years():
    assert cm.is_leap_year(2000) is True
    assert cm.is_leap_year(1900) is False
    assert cm.is_leap_year(2024) is True
    assert cm.is_leap_year(2023) is False
    assert cm.is_leap_year(0) is True          # year 0 = 1 BCE, divisible by 400
    assert cm.is_leap_year(-4) is True          # 5 BCE
    assert cm.days_in_month(2024, 2) == 29
    assert cm.days_in_month(1900, 2) == 28


def test_add_months_clamps_short_months():
    assert cm.add_months(2025, 1, 31, 1) == (2025, 2, 28)   # not leap
    assert cm.add_months(2024, 1, 31, 1) == (2024, 2, 29)   # leap
    assert cm.add_months(2025, 12, 15, 1) == (2026, 1, 15)  # year rollover
    assert cm.add_months(2025, 1, 15, -1) == (2024, 12, 15)


def test_add_years_clamps_feb29():
    assert cm.add_years(2024, 2, 29, 1) == (2025, 2, 28)
    assert cm.add_years(2024, 2, 29, 4) == (2028, 2, 29)


def test_format_year_bce_ce():
    assert cm.format_year(2026) == "2026 CE"
    assert cm.format_year(1) == "1 CE"
    assert cm.format_year(0) == "1 BCE"
    assert cm.format_year(-1) == "2 BCE"
    assert cm.format_year(-99) == "100 BCE"


def test_month_grid_basic():
    grid = cm.build_month_grid(2026, 9)
    assert grid.num_days == 30
    assert grid.total_cells % 7 == 0
    assert grid.total_cells >= grid.leading_blanks + grid.num_days


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"\nAll {len(tests)} calendar_math tests passed.")
