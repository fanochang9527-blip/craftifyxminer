"""Unit tests for pipeline.seed_import — category mapping and validation."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from pipeline.seed_import import CATEGORY_TO_CREATOR_TYPE, _validate_creator_type
from pipeline.seed_file_loader import load_seed_dataframe_from_xlsx


class TestCategoryMapping:
    def test_four_chinese_categories(self):
        assert CATEGORY_TO_CREATOR_TYPE["A-官方IP"] == "game_creator"
        assert CATEGORY_TO_CREATOR_TYPE["B-原创OC"] == "oc_creator"
        assert CATEGORY_TO_CREATOR_TYPE["C-虚拟IP"] == "vtuber"
        assert CATEGORY_TO_CREATOR_TYPE["E-二创IP"] == "fan_artist"


class TestValidateCreatorType:
    def test_category_column_auto_maps(self):
        df = pd.DataFrame(
            {
                "username": ["a", "b"],
                "category": ["B-原创OC", "C-虚拟IP"],
            }
        )
        _validate_creator_type(df)
        assert "creator_type" in df.columns
        assert list(df["creator_type"]) == ["oc_creator", "vtuber"]

    def test_creator_type_column_preserved(self):
        df = pd.DataFrame(
            {
                "username": ["x"],
                "creator_type": ["fan_artist"],
            }
        )
        _validate_creator_type(df)
        assert df["creator_type"].iloc[0] == "fan_artist"

    def test_missing_both_raises(self):
        df = pd.DataFrame({"username": ["x"]})
        with pytest.raises(ValueError, match="must include"):
            _validate_creator_type(df)

    def test_unknown_category_fallback(self):
        df = pd.DataFrame(
            {
                "username": ["x"],
                "category": ["Z-未知类型"],
            }
        )
        _validate_creator_type(df)
        assert df["creator_type"].iloc[0] == "unknown"


class TestLoadXlsx:
    def test_dedupe_keeps_max_transaction_count_then_total_sales(self, tmp_path: Path) -> None:
        """同一 (platform, platform_account_id)：成交笔数优先；相同时销售额大者优先。"""
        xlsx = tmp_path / "seed.xlsx"
        df_in = pd.DataFrame(
            {
                "twitter_handle": ["DupUser", "DupUser"],
                "category": ["B-原创OC", "B-原创OC"],
                "main_link": ["https://x.com/dup", "https://x.com/dup"],
                "total_sales": [99.0, 10.0],
                "transaction_count": [5, 100],
            }
        )
        df_in.to_excel(xlsx, index=False, engine="openpyxl")
        out, load_stats = load_seed_dataframe_from_xlsx(xlsx)
        assert len(out) == 1
        assert out["username"].iloc[0] == "dupuser"
        assert int(out["transaction_count"].iloc[0]) == 100
        assert float(out["total_sales"].iloc[0]) == 10.0
        assert load_stats["raw_rows"] == 2
        assert load_stats["dropped_empty_handle"] == 0
        assert load_stats["rows_after_dedupe"] == 1
        assert load_stats["merged_duplicate_rows"] == 1

    def test_dedupe_same_transaction_count_keeps_max_total_sales(self, tmp_path: Path) -> None:
        xlsx = tmp_path / "seed2.xlsx"
        df_in = pd.DataFrame(
            {
                "twitter_handle": ["Same", "Same"],
                "category": ["B-原创OC", "B-原创OC"],
                "total_sales": [50.0, 200.0],
                "transaction_count": [10, 10],
            }
        )
        df_in.to_excel(xlsx, index=False, engine="openpyxl")
        out, _ = load_seed_dataframe_from_xlsx(xlsx)
        assert len(out) == 1
        assert float(out["total_sales"].iloc[0]) == 200.0
