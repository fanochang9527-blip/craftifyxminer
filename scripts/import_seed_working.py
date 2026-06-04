"""临时脚本入口：将 seed_working.xlsx 中的合作中作者导入数据库。

用法：
    .venv/bin/python scripts/import_seed_working.py [--path data/seed_working.xlsx]
"""

import argparse
import logging
import sys

sys.path.insert(0, "/opt/craftifyxminer")

from pipeline.seed_working_import import import_seed_working

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_PATH = "data/seed_working.xlsx"


def main():
    parser = argparse.ArgumentParser(description="Import seed_working.xlsx into creators")
    parser.add_argument("--path", default=DEFAULT_PATH, help="Path to xlsx file")
    args = parser.parse_args()

    result = import_seed_working(args.path)
    print(result)


if __name__ == "__main__":
    main()
