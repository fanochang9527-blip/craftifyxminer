"""Full pipeline runner — 9 步日常流水线。

步骤:
  1. Generate anchors (全量种子)
  2. L1 scan (Apify following)
  3. Deep scrape
  4. Content style filter (multimodal)
  5. Type classification
  6. Feature computation
  7. Backfill creator_graph & centrality
  8. SPS prediction
  9. Model evaluation
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
        return True


def run_full_pipeline(
    *,
    anchors: list[dict] | None = None,
    deep_limit: int | None = None,
) -> dict:
    """Execute the full daily 9-step pipeline.

    Returns a summary dict of all step results.
    """
    from pipeline.backfill import run_backfill
    from pipeline.content_style_filter import filter_all_pending as _filter_content_style
    from pipeline.deep_scrape import trigger_deep_scrape_batch
    from pipeline.discovery import generate_daily_seeds, trigger_l1_scan
    from pipeline.feature_engine import compute_all_pending
    from pipeline.model_monitor import evaluate_model
    from pipeline.sps_scorer import score_all_pending
    from pipeline.type_classifier import classify_all_pending

    steps = [
        "Generate anchors (all seeds)",
        "L1 scan (Apify following)",
        "Deep scrape",
        "Content style filter (multimodal)",
        "Type classification",
        "Feature computation",
        "Backfill creator_graph & centrality",
        "SPS prediction",
        "Model evaluation",
        "Train sellability model",
        "Train SPS model",
    ]
    total = len(steps)
    start_time = time.time()
    start_ts = _ts()

    print(_SEP)
    print(f" CraftifyX Miner — Daily Pipeline (9-step)")
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
        "classified": 0,
        "content_style": {},
        "features": 0,
        "backfill": {},
        "scores": 0,
        "evaluation": {},
        "sellability_training": {},
        "sps_training": {},
        "errors": [],
    }

    # Step 1: anchors
    with _StepTimer(1, total, steps[0]) as st:
        if anchors is None:
            anchors = generate_daily_seeds()
        n = len(anchors)
        st.result_line = f"{n} anchors (all seeds)"
        summary["anchors"] = n
    if st.failed:
        summary["errors"].append(("anchors", st.result_line))

    # Step 2: L1 scan
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

    # Step 3: Deep scrape
    with _StepTimer(3, total, steps[2]) as st:
        ds_kwargs: dict = {}
        if deep_limit is not None:
            ds_kwargs["limit"] = deep_limit
        ds = trigger_deep_scrape_batch(**ds_kwargs)
        st.result_line = f"{ds.get('candidates', 0)} candidates, run_id={ds.get('run_id', 'N/A')}"
        summary["deep_scrape"] = ds
    if st.failed:
        summary["errors"].append(("deep_scrape", st.result_line))

    # Step 4: Content style filter (multimodal)
    with _StepTimer(4, total, steps[3]) as st:
        style_result = _filter_content_style()
        st.result_line = (
            f"{style_result.get('analyzed', 0)} analyzed, "
            f"{style_result.get('passed', 0)} passed, "
            f"{style_result.get('rejected', 0)} rejected, "
            f"{style_result.get('skipped', 0)} skipped"
        )
        summary["content_style"] = style_result
    if st.failed:
        summary["errors"].append(("content_style", st.result_line))

    # Step 5: Type classification
    with _StepTimer(5, total, steps[4]) as st:
        classified = classify_all_pending()
        st.result_line = f"{classified} creators classified"
        summary["classified"] = classified
    if st.failed:
        summary["errors"].append(("classification", st.result_line))

    # Step 6: Features
    with _StepTimer(6, total, steps[5]) as st:
        feat = compute_all_pending()
        st.result_line = f"{feat} creators computed"
        summary["features"] = feat
    if st.failed:
        summary["errors"].append(("features", st.result_line))

    # Step 7: Backfill creator_graph & centrality
    with _StepTimer(7, total, steps[6]) as st:
        backfill_result = run_backfill()
        st.result_line = (
            f"inserted {backfill_result.get('relations_inserted', 0)} graph edges, "
            f"updated {backfill_result.get('scores_updated', 0)} scores"
        )
        summary["backfill"] = backfill_result
    if st.failed:
        summary["errors"].append(("backfill", st.result_line))

    # Step 8: SPS prediction
    with _StepTimer(8, total, steps[7]) as st:
        scores = score_all_pending()
        st.result_line = f"{scores} creators scored"
        summary["scores"] = scores
    if st.failed:
        summary["errors"].append(("scores", st.result_line))

    # Step 9: Model evaluation
    with _StepTimer(9, total, steps[8]) as st:
        eval_results = evaluate_model()
        sell_result = next((r for r in eval_results if r.get("model_name") == "sellability"), {})
        sps_result = next((r for r in eval_results if r.get("model_name") == "sps"), {})
        recall = sell_result.get("recall", "N/A")
        p250 = sps_result.get("precision_at_250", "N/A")
        st.result_line = f"recall={recall}, P@250={p250}"
        summary["evaluation"] = {"sellability": sell_result, "sps": sps_result}
    if st.failed:
        summary["errors"].append(("evaluation", st.result_line))

    # Step 10: Train sellability model
    with _StepTimer(10, total, steps[9]) as st:
        from pipeline.sellability_model import train_model as _train_sellability
        train_meta = _train_sellability()
        st.result_line = f"{train_meta['model_type']} ({train_meta['n_samples']} samples)"
        summary["sellability_training"] = train_meta
    if st.failed:
        summary["errors"].append(("sellability_training", st.result_line))

    # Step 11: Train SPS model
    with _StepTimer(11, total, steps[10]) as st:
        from pipeline.sps_model import train_model as _train_sps
        train_meta = _train_sps()
        st.result_line = f"{train_meta['model_type']} ({train_meta['n_samples']} samples)"
        summary["sps_training"] = train_meta
    if st.failed:
        summary["errors"].append(("sps_training", st.result_line))

    # Summary
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
    cs_data = summary.get("content_style", {})
    if cs_data:
        print(f" Content style:       {cs_data.get('analyzed', 0)} analyzed, "
              f"{cs_data.get('passed', 0)} passed, "
              f"{cs_data.get('rejected', 0)} rejected")
    print(f" Type classified:     {summary['classified']}")
    print(f" Features computed:   {summary['features']}")
    backfill_data = summary.get("backfill", {})
    print(f" Backfill graph:      {backfill_data.get('relations_inserted', 0)} edges")
    print(f" Backfill scores:     {backfill_data.get('scores_updated', 0)} updated")
    print(f" Scores computed:     {summary['scores']}")
    eval_data = summary.get("evaluation", {})
    sell_result = eval_data.get("sellability", {}) if isinstance(eval_data, dict) else {}
    sps_result = eval_data.get("sps", {}) if isinstance(eval_data, dict) else {}
    if eval_data and not (sell_result.get("error") or sps_result.get("error")):
        print(f" Model eval:          recall={sell_result.get('recall')}, "
              f"P@250={sps_result.get('precision_at_250')}, "
              f"F2={sell_result.get('f2_score')}")
    sell_train = summary.get("sellability_training", {})
    if sell_train and not sell_train.get("error"):
        print(f" Sellability training: {sell_train.get('model_type')} ({sell_train.get('n_samples')} samples)")
    sps_train = summary.get("sps_training", {})
    if sps_train and not sps_train.get("error"):
        print(f" SPS training:         {sps_train.get('model_type')} ({sps_train.get('n_samples')} samples)")
    print(f" Total elapsed:       {total_elapsed:.1f}s")
    print(f" Status:              {status}")
    if summary["errors"]:
        print(f" Errors:")
        for step_name, err in summary["errors"]:
            print(f"   - {step_name}: {err}")
    print(_SEP)

    logger.info("Pipeline complete: %s in %.1fs", status, total_elapsed)
    return summary


def train_models() -> dict:
    """Train both ML models (sellability + SPS). Used by deployment scripts for cold-start.

    Returns a dict with training metadata for each model. Errors are caught and logged
    so that a failure in one model does not block the other.
    """
    from pipeline.sellability_model import train_model as _train_sellability
    from pipeline.sps_model import train_model as _train_sps

    results: dict = {}
    try:
        results["sellability"] = _train_sellability()
        logger.info("Sellability model trained: %s", results["sellability"]["model_type"])
    except Exception:
        logger.exception("Sellability model training failed")
        results["sellability"] = {"error": "training_failed"}

    try:
        results["sps"] = _train_sps()
        logger.info("SPS model trained: %s", results["sps"]["model_type"])
    except Exception:
        logger.exception("SPS model training failed")
        results["sps"] = {"error": "training_failed"}

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    run_full_pipeline()
