from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.config import Settings
from src.flows.business_hours import BusinessHours


def test_business_hours_use_local_time_and_half_open_intervals() -> None:
    hours = BusinessHours.model_validate(
        {
            "timezone": "America/Sao_Paulo",
            "intervals": [
                {"weekday": 0, "start": "09:00", "end": "12:00"},
                {"weekday": 0, "start": "13:00", "end": "18:00"},
            ],
        }
    )
    assert not hours.is_open(datetime(2035, 1, 1, 11, 59, tzinfo=UTC))
    assert hours.is_open(datetime(2035, 1, 1, 12, 0, tzinfo=UTC))
    assert not hours.is_open(datetime(2035, 1, 1, 15, 0, tzinfo=UTC))
    assert hours.is_open(datetime(2035, 1, 1, 16, 0, tzinfo=UTC))
    assert not hours.is_open(datetime(2035, 1, 1, 21, 0, tzinfo=UTC))
    assert not hours.is_open(datetime(2035, 1, 2, 12, 0, tzinfo=UTC))
    with pytest.raises(ValueError, match="timezone"):
        hours.is_open(datetime(2035, 1, 1, 12, 0))


@pytest.mark.parametrize(
    "schedule",
    [
        {"timezone": "invalid/zone", "intervals": []},
        {"timezone": "UTC", "intervals": [{"weekday": 7, "start": "09:00", "end": "10:00"}]},
        {"timezone": "UTC", "intervals": [{"weekday": 0, "start": "23:00", "end": "01:00"}]},
        {
            "timezone": "UTC",
            "intervals": [
                {"weekday": 0, "start": "09:00", "end": "12:00"},
                {"weekday": 0, "start": "11:00", "end": "13:00"},
            ],
        },
    ],
)
def test_invalid_schedules_are_rejected(schedule: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BusinessHours.model_validate(schedule)


def test_schedule_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "SIMULATOR_BUSINESS_HOURS",
        '{"timezone":"UTC","intervals":[{"weekday":0,"start":"09:00","end":"18:00"}]}',
    )
    settings = Settings()
    assert settings.simulator_business_hours is not None
    assert settings.simulator_business_hours.is_open(datetime(2035, 1, 1, 9, tzinfo=UTC))


def test_daylight_saving_transition_uses_timezone_database() -> None:
    hours = BusinessHours.model_validate(
        {
            "timezone": "America/New_York",
            "intervals": [{"weekday": 6, "start": "01:00", "end": "02:00"}],
        }
    )
    assert hours.is_open(datetime(2026, 11, 1, 5, 30, tzinfo=UTC))
    assert hours.is_open(datetime(2026, 11, 1, 6, 30, tzinfo=UTC))
    assert not hours.is_open(datetime(2026, 11, 1, 7, 0, tzinfo=UTC))
