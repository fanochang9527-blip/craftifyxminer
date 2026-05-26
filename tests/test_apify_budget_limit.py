"""Tests for Apify budget hard limit feature.

Covers:
- _check_budget() in deep_scrape
- trigger_l1_scan() budget gate in discovery
"""

from unittest.mock import patch

import pytest


# ------------------------------------------------------------------
# deep_scrape
# ------------------------------------------------------------------

@patch("pipeline.deep_scrape.fetch_one")
@patch("pipeline.deep_scrape.DAILY_APIFY_BUDGET_USD", 40.0)
@patch("pipeline.deep_scrape.APIFY_BUDGET_HARD_LIMIT", False)
def test_deep_scrape_soft_limit_continues(mock_fetch_one):
    """超预算但 hard_limit=false 时，_check_budget 返回 True（不阻断）。"""
    mock_fetch_one.return_value = {"today": 50.0}
    from pipeline.deep_scrape import _check_budget
    assert _check_budget() is True


@patch("pipeline.deep_scrape.fetch_one")
@patch("pipeline.deep_scrape.DAILY_APIFY_BUDGET_USD", 40.0)
@patch("pipeline.deep_scrape.APIFY_BUDGET_HARD_LIMIT", True)
def test_deep_scrape_hard_limit_blocks(mock_fetch_one):
    """超预算且 hard_limit=true 时，_check_budget 返回 False（阻断）。"""
    mock_fetch_one.return_value = {"today": 50.0}
    from pipeline.deep_scrape import _check_budget
    assert _check_budget() is False


# ------------------------------------------------------------------
# discovery
# ------------------------------------------------------------------

@patch("pipeline.discovery.fetch_one")
@patch("pipeline.discovery.DAILY_APIFY_BUDGET_USD", 40.0)
@patch("pipeline.discovery.APIFY_BUDGET_HARD_LIMIT", True)
def test_discovery_hard_limit_blocks(mock_fetch_one):
    """超预算且 hard_limit=true 时，trigger_l1_scan 返回 budget_ok=False。"""
    mock_fetch_one.return_value = {"today_cost": 50.0}
    from pipeline.discovery import trigger_l1_scan
    result = trigger_l1_scan(anchors=[])
    assert result == {"runs_started": 0, "budget_ok": False, "stored": 0}
