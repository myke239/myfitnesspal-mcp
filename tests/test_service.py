from datetime import date
from types import SimpleNamespace

import pytest

from myfitnesspal_mcp.service import AccessError, Service, date_range, parse_date


class FakeClient:
    effective_username = "test-user"

    def get_date(self, selected):
        totals = {"calories": 100.0, "protein": 10.0} if selected.day == 1 else {}
        entry = SimpleNamespace(name="food", nutrition_information=totals)
        meal = SimpleNamespace(name="breakfast", entries=[entry])
        return SimpleNamespace(
            complete=False,
            totals=totals,
            goals={},
            meals=[meal],
            water=250.0,
            exercises=[],
        )

    def get_measurements(self, measurement, lower_bound, upper_bound):
        return {lower_bound: 150.0}


@pytest.mark.parametrize("value", ["2026-1-01", "today", "2026-02-30", "20260101"])
def test_invalid_dates(value):
    with pytest.raises(ValueError):
        parse_date(value)


def test_range_boundaries():
    assert len(date_range("2026-01-01", "2026-01-31")) == 31
    assert date_range("2026-01-01", "2026-01-01") == [date(2026, 1, 1)]
    for start, end in [("2026-01-01", "2026-02-01"), ("2026-01-02", "2026-01-01")]:
        with pytest.raises(ValueError):
            date_range(start, end)


def test_missing_days_do_not_lower_average():
    result = Service(FakeClient).summary("2026-01-01", "2026-01-02")
    assert result["daily_averages"]["calories"] == 100
    assert result["days_with_each_nutrient"]["calories"] == 1
    assert result["requested_days"] == 2


def test_read_serialization():
    service = Service(FakeClient)
    assert service.diary("2026-01-01")["meals"][0]["entries"][0]["name"] == "food"
    assert service.water("2026-01-01")["water_ml"] == 250
    result = service.measurements("Weight", "2026-01-01", "2026-01-02")
    assert result["unit"] is None
    assert result["entries"] == [{"date": "2026-01-01", "value": 150.0}]


def test_invalid_range_never_authenticates():
    def forbidden():
        pytest.fail("Invalid input must not access cookies or network")

    with pytest.raises(ValueError):
        Service(forbidden).summary("2026-01-02", "2026-01-01")


def test_upstream_errors_are_sanitized_and_reset_client():
    def failed():
        raise RuntimeError("secret-cookie-token")

    service = Service(failed)
    with pytest.raises(AccessError) as error:
        service.connection_status()
    assert "secret" not in str(error.value)
    assert service._client is None
