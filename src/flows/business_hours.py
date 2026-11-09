from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


class BusinessInterval(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start: time
    end: time

    @model_validator(mode="after")
    def validate_interval(self) -> BusinessInterval:
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise ValueError("interval times must not include a timezone")
        if self.start >= self.end:
            raise ValueError("interval end must be later than start on the same day")
        return self


class BusinessHours(BaseModel):
    timezone: str
    intervals: list[BusinessInterval]

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("unknown IANA timezone") from error
        return value

    @model_validator(mode="after")
    def validate_intervals(self) -> BusinessHours:
        for day in range(7):
            intervals = sorted(
                (item for item in self.intervals if item.weekday == day),
                key=lambda item: item.start,
            )
            for previous, current in zip(intervals, intervals[1:], strict=False):
                if current.start < previous.end:
                    raise ValueError("business intervals must not overlap")
        return self

    def is_open(self, at: datetime) -> bool:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        local = at.astimezone(ZoneInfo(self.timezone))
        local_time = local.time()
        return any(
            item.weekday == local.weekday() and item.start <= local_time < item.end
            for item in self.intervals
        )
