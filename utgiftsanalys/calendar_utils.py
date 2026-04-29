from datetime import date, timedelta

import holidays


def _extra_bank_free_days(year: int) -> set[date]:
    """Days not in holidays.Sweden that are still bank-free in Sweden."""
    extra = set()
    # Julafton (Christmas Eve) and Nyårsafton (New Year's Eve)
    extra.add(date(year, 12, 24))
    extra.add(date(year, 12, 31))
    # Midsommarafton: Friday immediately before Midsommardagen.
    # Midsommardagen is the Saturday between Jun 20–26.
    for day in range(20, 27):
        d = date(year, 6, day)
        if d.weekday() == 5:  # Saturday = Midsommardagen
            extra.add(d - timedelta(days=1))  # Friday before = Midsommarafton
            break
    return extra


def swedish_bank_days(year: int, month: int) -> list[date]:
    """Return sorted list of bank days (Mon–Fri, non-holiday) in the given month."""
    se_holidays = holidays.Sweden(years=[year])  # type: ignore[attr-defined]
    extra = _extra_bank_free_days(year)
    result = []
    d = date(year, month, 1)
    while d.month == month:
        if d.weekday() < 5 and d not in se_holidays and d not in extra:
            result.append(d)
        d += timedelta(days=1)
    return result


def get_analysis_month(booking_date: date) -> str:
    """Return 'YYYY-MM' for the analysis month of a booking date.

    The first bank day of month M belongs to M-1; second and later belong to M.
    """
    y, m = booking_date.year, booking_date.month
    bank_days = swedish_bank_days(y, m)
    first_bd = bank_days[0]

    if booking_date <= first_bd:
        if m == 1:
            return f"{y - 1}-12"
        return f"{y}-{m - 1:02d}"
    return f"{y}-{m:02d}"
