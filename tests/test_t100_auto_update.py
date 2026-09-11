"""Fast tests for T-100 freshness scheduling decisions."""

from datetime import date

from pipeline.auto_update_bts import next_period, periods_to_check


def test_next_period_rolls_year_boundary():
    assert next_period((2025, 12)) == (2026, 1)
    assert next_period((2026, 5)) == (2026, 6)


def test_periods_stop_before_current_month():
    assert periods_to_check((2026, 5), date(2026, 9, 11)) == [
        (2026, 6), (2026, 7), (2026, 8)
    ]


def test_empty_latest_starts_at_january_of_current_year():
    assert periods_to_check(None, date(2026, 4, 2)) == [
        (2026, 1), (2026, 2), (2026, 3)
    ]
