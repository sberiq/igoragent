from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import random
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator


class HeartbeatMode(StrEnum):
    DISABLED = "disabled"
    FIXED_INTERVAL = "fixed_interval"
    RANDOM_RUNS_PER_HOUR = "random_runs_per_hour"


class HeartbeatSettings(BaseModel):
    mode: HeartbeatMode = HeartbeatMode.DISABLED
    interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    max_runs_per_hour: int | None = Field(default=None, ge=1, le=60)
    timezone: str = "UTC"

    @model_validator(mode="after")
    def validate_mode(self) -> "HeartbeatSettings":
        if self.mode is HeartbeatMode.FIXED_INTERVAL and self.interval_minutes is None:
            raise ValueError("fixed_interval requires interval_minutes")
        if self.mode is HeartbeatMode.RANDOM_RUNS_PER_HOUR and self.max_runs_per_hour is None:
            raise ValueError("random_runs_per_hour requires max_runs_per_hour")
        if self.mode is not HeartbeatMode.FIXED_INTERVAL and self.interval_minutes is not None:
            raise ValueError("interval_minutes is valid only for fixed_interval")
        if self.mode is not HeartbeatMode.RANDOM_RUNS_PER_HOUR and self.max_runs_per_hour is not None:
            raise ValueError("max_runs_per_hour is valid only for random_runs_per_hour")
        ZoneInfo(self.timezone)
        return self


class HeartbeatSchedule(BaseModel):
    hour: datetime
    run_at: list[datetime]


def plan_hourly_heartbeat(settings: HeartbeatSettings, hour: datetime, seed: str) -> HeartbeatSchedule:
    if settings.mode is not HeartbeatMode.RANDOM_RUNS_PER_HOUR:
        return HeartbeatSchedule(hour=hour.replace(minute=0, second=0, microsecond=0), run_at=[])

    local_hour = hour.astimezone(ZoneInfo(settings.timezone)).replace(minute=0, second=0, microsecond=0)
    count = settings.max_runs_per_hour or 0
    identity = f"{seed}:{local_hour.isoformat()}".encode()
    rng = random.Random(hashlib.sha256(identity).digest())
    offsets = sorted(rng.sample(range(60 * 60), k=count))
    return HeartbeatSchedule(
        hour=local_hour,
        run_at=[local_hour + timedelta(seconds=offset) for offset in offsets],
    )
