"""
calendar_math.py
=================

The "infinite calendar" engine.

Python's built-in ``datetime`` module only understands years 1-9999. That is
fine for everyday use, but this project promises the user can jump to *any*
date - year 50,000 CE, year -12,000 (i.e. 12,001 BCE), whatever they type in.

To do that we don't use ``datetime`` at all for navigation. Instead we treat
every calendar date as a single integer: the number of days since a fixed
reference point (1970-01-01), called an "epoch day" or "ordinal day" here.
Once a date is an integer, moving forward/backward in time is just addition
and subtraction, and Python integers have no size limit - so the calendar
really has no edge.

The conversion between (year, month, day) <-> epoch_day is done with a
well-known, public-domain integer algorithm for the *proleptic Gregorian
calendar* (i.e. the modern calendar rules extended backwards and forwards
forever, ignoring the fact that most countries didn't actually use the
Gregorian calendar before 1582). This exact algorithm is used by C++'s
<chrono> library and many other date libraries. It is pure integer math
(floor division only) so it is fast and never loses precision, even for
huge years.

Year numbering used here is "astronomical": year 0 = 1 BCE, year -1 = 2 BCE,
year -100 = 101 BCE, and so on. ``format_year`` converts that back to the
human-friendly "123 BCE" / "2026 CE" style for display.
"""

from __future__ import annotations

from dataclasses import dataclass

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday",
                  "Thursday", "Friday", "Saturday"]

_DAYS_IN_MONTH_COMMON = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def is_leap_year(year: int) -> bool:
    """True if `year` is a leap year, under the Gregorian rule extended
    infinitely in both directions (works correctly for negative years
    too, since Python's % always returns a same-sign-as-divisor result)."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_month(year: int, month: int) -> int:
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1-12, got {month}")
    if month == 2 and is_leap_year(year):
        return 29
    return _DAYS_IN_MONTH_COMMON[month - 1]


def to_epoch_day(year: int, month: int, day: int) -> int:
    """Convert a (year, month, day) triple to a single integer: the number
    of days since 1970-01-01 (negative for earlier dates). This is the
    'days_from_civil' algorithm - public-domain integer date math that is
    correct for the entire proleptic Gregorian calendar."""
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1-12, got {month}")
    if not 1 <= day <= days_in_month(year, month):
        raise ValueError(f"day {day} is not valid for {year}-{month:02d}")

    y = year - 1 if month <= 2 else year
    # NOTE: the classic C++ version of this algorithm special-cases negative
    # numerators here (`y - 399` before dividing) because C++ integer
    # division truncates toward zero. Python's `//` is already a *floor*
    # division (rounds toward -infinity), which is what this algorithm
    # actually needs - so in Python we must use plain floor division with
    # no special-casing, or negative years come out one era off.
    era = y // 400
    yoe = y - era * 400                                   # [0, 399]
    mp = (month + 9) % 12                                 # Mar=0 .. Feb=11
    doy = (153 * mp + 2) // 5 + day - 1                    # [0, 365]
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy          # [0, 146096]
    return era * 146097 + doe - 719468


def from_epoch_day(epoch_day: int) -> tuple[int, int, int]:
    """Inverse of `to_epoch_day`: integer day count -> (year, month, day)."""
    z = epoch_day + 719468
    # Same note as in to_epoch_day: plain floor division, no truncation
    # workaround needed in Python.
    era = z // 146097
    doe = z - era * 146097                                          # [0, 146096]
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365  # [0, 399]
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)                  # [0, 365]
    mp = (5 * doy + 2) // 153                                        # [0, 11]
    day = doy - (153 * mp + 2) // 5 + 1                              # [1, 31]
    month = mp + 3 if mp < 10 else mp - 9                            # [1, 12]
    year = y + 1 if month <= 2 else y
    return year, month, day


def weekday_index(year: int, month: int, day: int) -> int:
    """0 = Sunday, 1 = Monday, ... 6 = Saturday. 1970-01-01 (epoch day 0)
    was a Thursday, which anchors the whole infinite sequence."""
    epoch_day = to_epoch_day(year, month, day)
    return (epoch_day + 4) % 7


def add_days(year: int, month: int, day: int, delta: int) -> tuple[int, int, int]:
    return from_epoch_day(to_epoch_day(year, month, day) + delta)


def add_months(year: int, month: int, day: int, delta: int) -> tuple[int, int, int]:
    """Shift by whole months, clamping the day if the target month is
    shorter (e.g. Jan 31 + 1 month -> Feb 28/29, not an error)."""
    total = year * 12 + (month - 1) + delta
    new_year, new_month0 = divmod(total, 12)
    new_month = new_month0 + 1
    new_day = min(day, days_in_month(new_year, new_month))
    return new_year, new_month, new_day


def add_years(year: int, month: int, day: int, delta: int) -> tuple[int, int, int]:
    new_year = year + delta
    new_day = min(day, days_in_month(new_year, month))
    return new_year, month, new_day


def format_year(year: int) -> str:
    """Astronomical year 0 -> '1 BCE', -1 -> '2 BCE', 2026 -> '2026 CE'."""
    if year <= 0:
        return f"{1 - year} BCE"
    return f"{year} CE"


def format_date(year: int, month: int, day: int) -> str:
    return f"{MONTH_NAMES[month - 1]} {day}, {format_year(year)}"


@dataclass(frozen=True)
class MonthGrid:
    """A ready-to-render month: which weekday it starts on and how many
    days it has. The UI turns this into a 6x7 grid of cells."""
    year: int
    month: int
    first_weekday: int   # 0=Sun .. 6=Sat, weekday of the 1st of the month
    num_days: int

    @property
    def leading_blanks(self) -> int:
        return self.first_weekday

    @property
    def total_cells(self) -> int:
        # round up to a multiple of 7 so the grid always has full weeks
        filled = self.leading_blanks + self.num_days
        return ((filled + 6) // 7) * 7


def build_month_grid(year: int, month: int) -> MonthGrid:
    first_weekday = weekday_index(year, month, 1)
    num_days = days_in_month(year, month)
    return MonthGrid(year=year, month=month,
                      first_weekday=first_weekday, num_days=num_days)
