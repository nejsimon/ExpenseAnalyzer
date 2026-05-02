from datetime import date

from utgiftsanalys.calendar_utils import current_analysis_month, get_analysis_month, swedish_bank_days


def test_bank_days_excludes_weekends():
    days = swedish_bank_days(2026, 1)
    assert all(d.weekday() < 5 for d in days)


def test_bank_days_excludes_new_years():
    days = swedish_bank_days(2026, 1)
    assert date(2026, 1, 1) not in days


def test_bank_days_sorted():
    days = swedish_bank_days(2026, 4)
    assert days == sorted(days)


def test_analysis_month_first_bank_day_goes_to_previous():
    # 2026-01-02 is the first bank day of January 2026 (Jan 1 is holiday)
    days = swedish_bank_days(2026, 1)
    first_bd = days[0]
    result = get_analysis_month(first_bd)
    assert result == "2025-12"


def test_analysis_month_second_bank_day_stays_in_month():
    days = swedish_bank_days(2026, 1)
    second_bd = days[1]
    result = get_analysis_month(second_bd)
    assert result == "2026-01"


def test_analysis_month_january_boundary():
    # A date well into January should stay in January
    result = get_analysis_month(date(2026, 1, 15))
    assert result == "2026-01"


def test_analysis_month_regular_date():
    result = get_analysis_month(date(2026, 4, 15))
    assert result == "2026-04"


def test_bank_days_excludes_easter_monday():
    # Easter Monday 2026 = April 6
    days = swedish_bank_days(2026, 4)
    assert date(2026, 4, 6) not in days


def test_bank_days_excludes_midsommarafton():
    # Midsommarafton 2026 = June 19 (Friday before Midsommardagen June 20)
    days = swedish_bank_days(2026, 6)
    assert date(2026, 6, 19) not in days


def test_bank_days_excludes_julafton():
    days = swedish_bank_days(2026, 12)
    assert date(2026, 12, 24) not in days


def test_bank_days_excludes_nyarsafton():
    days = swedish_bank_days(2026, 12)
    assert date(2026, 12, 31) not in days


def test_current_analysis_month_on_first_bank_day_returns_previous():
    first_bd_may = swedish_bank_days(2026, 5)[0]
    assert current_analysis_month(reference=first_bd_may) == "2026-04"


def test_current_analysis_month_on_second_bank_day_returns_current():
    second_bd_may = swedish_bank_days(2026, 5)[1]
    assert current_analysis_month(reference=second_bd_may) == "2026-05"
