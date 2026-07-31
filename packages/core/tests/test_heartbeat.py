from datetime import datetime

import pytest

from igoragent_core.scheduler.heartbeat import HeartbeatMode, HeartbeatSettings, plan_hourly_heartbeat


def test_random_hourly_plan_is_deterministic_and_bounded() -> None:
    settings = HeartbeatSettings(
        mode=HeartbeatMode.RANDOM_RUNS_PER_HOUR,
        max_runs_per_hour=4,
        timezone="UTC",
    )
    hour = datetime.fromisoformat("2026-07-31T12:34:56+00:00")
    first = plan_hourly_heartbeat(settings, hour, "agent-a")
    second = plan_hourly_heartbeat(settings, hour, "agent-a")
    assert first.run_at == second.run_at
    assert len(first.run_at) == 4
    assert first.run_at == sorted(first.run_at)
    assert len(set(first.run_at)) == 4
    assert all(run.hour == 12 for run in first.run_at)


def test_heartbeat_rejects_mixed_modes() -> None:
    with pytest.raises(ValueError):
        HeartbeatSettings(
            mode=HeartbeatMode.FIXED_INTERVAL,
            interval_minutes=15,
            max_runs_per_hour=2,
        )
