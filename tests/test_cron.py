"""Tests for cron/daily_job.py — misfire grace time configuration."""

import pytest

from cron.daily_job import scheduler


@pytest.fixture(scope="module", autouse=True)
def remove_jobs():
    """Ensure jobs registered by module import are present."""
    # Module-level registration happens at import time; jobs should already exist.
    yield


def test_daily_pipeline_misfire_grace_time():
    job = scheduler.get_job("daily_pipeline")
    assert job is not None
    assert job.misfire_grace_time == 7200


def test_backfill_graph_misfire_grace_time():
    job = scheduler.get_job("backfill_graph")
    assert job is not None
    assert job.misfire_grace_time == 3600


def test_backfill_features_misfire_grace_time():
    job = scheduler.get_job("backfill_features")
    assert job is not None
    assert job.misfire_grace_time == 3600


def test_daily_summary_misfire_grace_time():
    job = scheduler.get_job("daily_summary")
    assert job is not None
    assert job.misfire_grace_time == 21600
