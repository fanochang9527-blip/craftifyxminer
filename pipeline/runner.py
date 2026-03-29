"""Full pipeline runner with structured logging.

Provides `run_full_pipeline()` — the single entry-point for both manual
invocation (`docker compose run ... server python -m pipeline.runner`)
and the cron scheduler.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

_SEP = "=" * 60
_THIN = "-" * 60


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class _StepTimer:
    """Context manager that times a step and captures its result line."""

    def __init__(self, idx: int, total: int, label: str):
        self.idx = idx
        self.total = total
        self.label = label
        self.start = 0.0
        self.elapsed = 0.0
        self.result_line = ""
        self.failed = False

    def __enter__(self):
        tag = f"[{self.idx}/{self.total}]"
        msg = f"{tag} {self.label} ..."
        print(msg, flush=True)
        logger.info(msg)
        self.start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.elapsed = time.time() - self.start
        if exc_type is not None:
            self.failed = True
            self.result_line = f"FAILED: {exc_val}"
        line = f"  -> {self.result_line:<52s} {self.elapsed:.1f}s"
        print(line, flush=True)
        logger.info(line.strip())
        print(flush=True)
        return True  # suppress exception so pipeline continues


def run_full_pipeline(
    *,
    anchors: list[dict] | None = None,
    deep_limit: int | None = None,
) -> dict:
    """Execute the full daily pipeline with structured logging.

    Returns a summary dict of all step results.
    """
    from pipeline.deep_scrape import trigger_deep_scrape_batch
    from pipeline.discovery import generate_daily_seeds, trigger_l1_scan
    from pipeline.feature_engine import compute_all_pending
    from pipeline.sps_scorer import score_all_pending

    steps = [
        "Generate anchors",
        "L1 scan (Apify following)",
        "Deep scrape",
        "Feature computation",
        "SPS scoring",
    ]
    total = len(steps)
    start_time = time.time()
    start_ts = _ts()

    # ---- Header ----
    print(_SEP)
    print(f" CraftifyX Miner — Daily Pipeline")
    print(f" Date: {start_ts}")
    print(_SEP)
    print(" Tasks:")
    for i, s in enumerate(steps, 1):
        print(f"  [{i}/{total}] {s}")
    print(_SEP)
    print(flush=True)

    summary: dict = {
        "start": start_ts,
        "anchors": 0,
        "l1": {},
        "deep_scrape": {},
        "features": 0,
        "scores": 0,
        "errors": [],
    }

    # ---- Step 1: anchors ----
    with _StepTimer(1, total, steps[0]) as st:
        if anchors is None:
            anchors = generate_daily_seeds()
        n = len(anchors)
        seed_count = sum(1 for a in anchors if a.get("strategy") == "seed_following")
        explore_count = n - seed_count
        st.result_line = f"{n} anchors ({seed_count} seed + {explore_count} explore)"
        summary["anchors"] = n
    if st.failed:
        summary["errors"].append(("anchors", st.result_line))

    # ---- Step 2: L1 scan ----
    with _StepTimer(2, total, steps[1]) as st:
        l1 = trigger_l1_scan(anchors=anchors)
        stored = l1.get("stored", {})
        store_info = stored.get("store", {})
        filter_info = stored.get("filter", {})
        st.result_line = (
            f"stored {store_info.get('total', 0)}, "
            f"passed {filter_info.get('rule_passed', 0)}+{filter_info.get('ai_passed', 0)} / "
            f"rejected {filter_info.get('rule_rejected', 0)}+{filter_info.get('ai_rejected', 0)} / "
            f"grey {filter_info.get('grey_zone', 0)}"
        )
        summary["l1"] = l1
    if st.failed:
        summary["errors"].append(("l1", st.result_line))

    # ---- Step 3: Deep scrape ----
    with _StepTimer(3, total, steps[2]) as st:
        ds_kwargs: dict = {}
        if deep_limit is not None:
            ds_kwargs["limit"] = deep_limit
        ds = trigger_deep_scrape_batch(**ds_kwargs)
        st.result_line = f"{ds.get('candidates', 0)} candidates, run_id={ds.get('run_id', 'N/A')}"
        summary["deep_scrape"] = ds
    if st.failed:
        summary["errors"].append(("deep_scrape", st.result_line))

    # ---- Step 4: Features ----
    with _StepTimer(4, total, steps[3]) as st:
        feat = compute_all_pending()
        st.result_line = f"{feat} creators computed"
        summary["features"] = feat
    if st.failed:
        summary["errors"].append(("features", st.result_line))

    # ---- Step 5: SPS scoring ----
    with _StepTimer(5, total, steps[4]) as st:
        scores = score_all_pending()
        st.result_line = f"{scores} creators scored"
        summary["scores"] = scores
    if st.failed:
        summary["errors"].append(("scores", st.result_line))

    # ---- Summary ----
    total_elapsed = time.time() - start_time
    status = "SUCCESS" if not summary["errors"] else "PARTIAL FAILURE"
    summary["elapsed"] = round(total_elapsed, 1)
    summary["status"] = status

    l1_data = summary.get("l1", {})
    l1_store = l1_data.get("stored", {}).get("store", {}) if isinstance(l1_data, dict) else {}
    l1_filter = l1_data.get("stored", {}).get("filter", {}) if isinstance(l1_data, dict) else {}
    ds_data = summary.get("deep_scrape", {})

    print(_SEP)
    print(" Summary")
    print(_THIN)
    print(f" Anchors generated:   {summary['anchors']}")
    print(f" L1 stored:           {l1_store.get('total', 0)} "
          f"(passed {l1_filter.get('rule_passed', 0)}+{l1_filter.get('ai_passed', 0)}, "
          f"rejected {l1_filter.get('rule_rejected', 0)}+{l1_filter.get('ai_rejected', 0)})")
    print(f" Deep scraped:        {ds_data.get('candidates', 0)}")
    print(f" Features computed:   {summary['features']}")
    print(f" Scores computed:     {summary['scores']}")
    print(f" Total elapsed:       {total_elapsed:.1f}s")
    print(f" Status:              {status}")
    if summary["errors"]:
        print(f" Errors:")
        for step_name, err in summary["errors"]:
            print(f"   - {step_name}: {err}")
    print(_SEP)

    logger.info("Pipeline complete: %s in %.1fs", status, total_elapsed)
    return summary


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    run_full_pipeline()
