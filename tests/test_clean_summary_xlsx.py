"""Unit tests for scripts.clean_summary_xlsx helpers."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from scripts.clean_summary_xlsx import (
    _clean_price,
    _clean_quantity,
    _clean_sku,
    _extract_links,
    _process_ad_link,
)


class TestCleanPrice:
    def test_parses_dollar_sign(self):
        assert _clean_price("$29.99") == 29.99

    def test_parses_plain_number(self):
        assert _clean_price("26.99") == 26.99

    def test_rejects_zero(self):
        assert _clean_price("0") is None

    def test_rejects_negative(self):
        assert _clean_price("-10") is None

    def test_rejects_empty(self):
        assert _clean_price("") is None
        assert _clean_price(np.nan) is None

    def test_rejects_invalid_string(self):
        assert _clean_price("unknown") is None


class TestCleanQuantity:
    def test_parses_integer(self):
        assert _clean_quantity("107") == 107.0

    def test_parses_float(self):
        assert _clean_quantity("107.5") == 107.5

    def test_rejects_zero(self):
        assert _clean_quantity(0) is None

    def test_rejects_negative(self):
        assert _clean_quantity(-5) is None

    def test_rejects_nan(self):
        assert _clean_quantity(np.nan) is None


class TestCleanSku:
    def test_joins_multiple_lines(self):
        assert _clean_sku("H-001\nH-002\nname") == "H-001 | H-002 | name"

    def test_single_line(self):
        assert _clean_sku("H-001") == "H-001"

    def test_strips_whitespace(self):
        assert _clean_sku("  H-001  ") == "H-001"

    def test_rejects_empty(self):
        assert _clean_sku("") is None
        assert _clean_sku(np.nan) is None


class TestExtractLinks:
    def test_single_link(self):
        links = _extract_links("https://x.com/user")
        assert links == ["https://x.com/user"]

    def test_multiple_newline_links(self):
        links = _extract_links("https://x.com/user\nhttps://youtube.com/u")
        assert links == ["https://x.com/user", "https://youtube.com/u"]

    def test_extracts_labeled_x_link(self):
        links = _extract_links("Twitter: https://x.com/user1")
        assert "https://x.com/user1" in links

    def test_splits_concatenated_platform_name(self):
        # n_kamuiinstagram 应该拆成 n_kamui
        links = _extract_links(
            "X：http://x.com/n_kamuiinstagram：http://www.instagram.com/natsuki_kamui/"
        )
        assert links == ["https://x.com/n_kamui"]

    def test_trims_trailing_platform_in_query(self):
        links = _extract_links("https://x.com/baimonbluewhale?mx=2Facebook")
        assert links == ["https://x.com/baimonbluewhale?mx=2"]

    def test_empty(self):
        assert _extract_links("") == []
        assert _extract_links(np.nan) == []


class TestProcessAdLink:
    def test_single_x_link(self):
        all_links, x_links, x_link, is_multi = _process_ad_link("https://x.com/user1")
        assert x_link == "https://x.com/user1"
        assert is_multi is False

    def test_multi_platform(self):
        all_links, x_links, x_link, is_multi = _process_ad_link(
            "https://x.com/user1\nhttps://instagram.com/user1"
        )
        assert x_link == "https://x.com/user1"
        assert is_multi is True

    def test_no_x_link(self):
        all_links, x_links, x_link, is_multi = _process_ad_link(
            "https://instagram.com/user1"
        )
        assert x_link is None
        assert x_links == []

    def test_x_and_twitter_same_platform(self):
        all_links, x_links, x_link, is_multi = _process_ad_link(
            "https://x.com/user1\nhttps://twitter.com/user1"
        )
        assert is_multi is False
