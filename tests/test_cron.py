"""Tests for cron/daily_job.py — schedule and misfire grace time configuration."""

import pytest

from cron.daily_job import scheduler


@pytest.fixture(scope="module", autouse=True)
def remove_jobs():
    """Ensure jobs registered by module import are present."""
    # Module-level registration happens at import time; jobs should already exist.
    yield


@pytest.mark.parametrize(
    "job_id,expected_hour,expected_minute,expected_grace_time",
    [
        ("daily_pipeline", 0, 0, 7200),
        ("backfill_graph", 1, 0, 3600),
        ("backfill_features", 2, 0, 3600),
        ("growth_monitor", 3, 0, 3600),
        ("daily_summary", 22, 0, 21600),
        ("follower_refresh", 23, 0, 3600),
    ],
)
def test_cron_job_schedule(job_id, expected_hour, expected_minute, expected_grace_time):
    job = scheduler.get_job(job_id)
    assert job is not None, f"Job {job_id} is not registered"
    assert job.misfire_grace_time == expected_grace_time
    trigger = job.trigger
    assert trigger.fields[trigger.FIELD_NAMES.index("hour")].expressions[0].first == expected_hour
    assert trigger.fields[trigger.FIELD_NAMES.index("minute")].expressions[0].first == expected_minute
