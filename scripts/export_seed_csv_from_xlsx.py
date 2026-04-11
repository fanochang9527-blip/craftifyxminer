"""从权威 xlsx 导出与 seed_import 兼容的 CSV（去重规则与 load_seed_dataframe_from_xlsx 一致：
(platform, platform_account_id) 唯一；多行时保留成交笔数最大，其次 total_sales）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from pipeline.seed_file_loader import load_seed_dataframe_from_xlsx  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Export seed CSV from 创作者账号链接及销量收集 style xlsx")
    p.add_argument(
        "--input",
        "-i",
        default=str(PROJECT / "data" / "创作者账号链接及销量收集.xlsx"),
        help="Path to xlsx",
    )
    p.add_argument(
        "--output",
        "-o",
        default=str(PROJECT / "data" / "creators_seed_from_xlsx.csv"),
        help="Output CSV path",
    )
    args = p.parse_args()

    df, _ = load_seed_dataframe_from_xlsx(args.input)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"Wrote {len(df)} rows -> {out}")


if __name__ == "__main__":
    main()
