"""v0.10.8 calibration diagnostics for dupe-engine runs.

This module is intentionally additive and stdlib-only. It can be run from inside
an existing dupe-engine checkout without changing the detection pipeline.

Primary goals:
- distinguish inherited/bootstrap champions from newly executed candidates
- summarize plateau behavior and throughput
- aggregate false-negative reason buckets
- compare exact variants and logical variant families across corpora
- emit reviewable JSON/Markdown/CSV artifacts for calibration decisions
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "dupe_engine_calibration_diagnostics_v0_10_8"


# -----------------------------
# parsing helpers
# -----------------------------

def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _as_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    s = str(value).strip()
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _as_int(value: Any, default: int = 0) -> int:
    f = _as_float(value, None)
    if f is None:
        return default
    return int(f)


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _json_cell(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    s = str(value).strip()
    if not s:
        return {}
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _round4(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _safe_div(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


_LOOP_RE = re.compile(r"^loop(?P<idx>\d+)_")


def loop_index(run_id: str | None) -> int | None:
    if not run_id:
        return None
    m = _LOOP_RE.match(str(run_id))
    if not m:
        return None
    try:
        return int(m.group("idx"))
    except ValueError:
        return None


def variant_family(variant_id: str | None) -> str:
    if not variant_id:
        return "unknown"
    return _LOOP_RE.sub("", str(variant_id), count=1)


def source_bucket(row: dict[str, Any], current_iteration_count: int | None) -> str:
    """Classify whether a scorecard row is plausibly from this run or bootstrap.

    v0.10.7 scorecards can include bootstrap rows with reused=false. The most
    reliable generic clue is the loop index compared with the current run's
    iteration_count. Example: a p4 run with iteration_count=3 can still carry a
    loop04_* champion from its bootstrap run.
    """
    idx = loop_index(str(row.get("run_id") or ""))
    if current_iteration_count is not None and idx is not None and idx > current_iteration_count:
        return "inherited_or_bootstrap"
    if _as_bool(row.get("reused"), False):
        return "reused"
    return "current_run"


def _metric(row: dict[str, Any], metric_name: str) -> float | None:
    return _as_float(row.get(metric_name), None)


def _sum_reason_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        cell = row.get("false_negative_reason_counts")
        for key, value in _json_cell(cell).items():
            counts[str(key)] += _as_int(value)
    return dict(counts)


def _sum_selection_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        cell = row.get("openai_ocr_selection_reason_counts")
        for key, value in _json_cell(cell).items():
            counts[str(key)] += _as_int(value)
    return dict(counts)


# -----------------------------
# aggregation
# -----------------------------

@dataclass
class VariantSummary:
    variant_id: str
    family: str
    source: str
    run_count: int
    corpus_count: int
    corpora: list[str]
    avg_metric: float | None
    worst_metric: float | None
    best_metric: float | None
    total_unknown_predictions: int
    total_known_negative_hits: int
    max_candidates_per_100_pages: float | None
    total_runtime_seconds: float
    total_openai_ocr_attempted: int
    total_embedding_calls: int
    false_negative_reason_counts: dict[str, int]
    ocr_selection_reason_counts: dict[str, int]


def aggregate_variants(
    scorecard_rows: list[dict[str, Any]],
    *,
    metric_name: str,
    current_iteration_count: int | None,
    source_filter: str | None = None,
) -> list[VariantSummary]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in scorecard_rows:
        if str(row.get("status") or "").strip().lower() not in {"", "succeeded", "success"}:
            continue
        if _metric(row, metric_name) is None:
            continue
        bucket = source_bucket(row, current_iteration_count)
        if source_filter is not None and bucket != source_filter:
            continue
        groups[(str(row.get("variant_id") or "unknown"), bucket)].append(row)

    summaries: list[VariantSummary] = []
    for (variant_id, bucket), rows in groups.items():
        values = [_metric(row, metric_name) for row in rows]
        values = [v for v in values if v is not None]
        corpora = sorted({str(row.get("corpus_id") or "unknown") for row in rows})
        max_candidates = [_as_float(row.get("candidates_per_100_pages"), None) for row in rows]
        max_candidates = [v for v in max_candidates if v is not None]
        summaries.append(
            VariantSummary(
                variant_id=variant_id,
                family=variant_family(variant_id),
                source=bucket,
                run_count=len(rows),
                corpus_count=len(corpora),
                corpora=corpora,
                avg_metric=_round4(sum(values) / len(values)) if values else None,
                worst_metric=_round4(min(values)) if values else None,
                best_metric=_round4(max(values)) if values else None,
                total_unknown_predictions=sum(_as_int(row.get("unknown_predictions")) for row in rows),
                total_known_negative_hits=sum(_as_int(row.get("known_negative_hits")) for row in rows),
                max_candidates_per_100_pages=_round4(max(max_candidates)) if max_candidates else None,
                total_runtime_seconds=round(sum(_as_float(row.get("runtime_seconds"), 0.0) or 0.0 for row in rows), 2),
                total_openai_ocr_attempted=sum(_as_int(row.get("openai_ocr_attempted")) for row in rows),
                total_embedding_calls=sum(_as_int(row.get("embedding_calls")) for row in rows),
                false_negative_reason_counts=_sum_reason_counts(rows),
                ocr_selection_reason_counts=_sum_selection_counts(rows),
            )
        )
    return sorted(
        summaries,
        key=lambda s: (
            s.worst_metric if s.worst_metric is not None else -1,
            s.avg_metric if s.avg_metric is not None else -1,
            -(s.total_known_negative_hits),
            -(s.total_unknown_predictions),
        ),
        reverse=True,
    )


def aggregate_family_by_corpus(
    scorecard_rows: list[dict[str, Any]],
    *,
    metric_name: str,
    current_iteration_count: int | None,
) -> list[dict[str, Any]]:
    """Return best row per logical family/corpus for split-strategy diagnosis.

    This is not an accepted candidate. It is a hint that different corpora may
    prefer different members of the same family.
    """
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in scorecard_rows:
        if source_bucket(row, current_iteration_count) != "current_run":
            continue
        value = _metric(row, metric_name)
        if value is None:
            continue
        fam = variant_family(str(row.get("variant_id") or "unknown"))
        corpus_id = str(row.get("corpus_id") or "unknown")
        key = (fam, corpus_id)
        existing = groups.get(key)
        if existing is None or (value > (_metric(existing, metric_name) or -1)):
            groups[key] = row

    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (fam, _), row in groups.items():
        by_family[fam].append(row)

    summaries: list[dict[str, Any]] = []
    for fam, rows in by_family.items():
        values = [_metric(row, metric_name) for row in rows]
        values = [v for v in values if v is not None]
        if not values:
            continue
        summaries.append(
            {
                "family": fam,
                "corpus_count": len(rows),
                "worst_metric": _round4(min(values)),
                "avg_metric": _round4(sum(values) / len(values)),
                "best_metric": _round4(max(values)),
                "corpus_best": {
                    str(row.get("corpus_id") or "unknown"): {
                        "run_id": row.get("run_id"),
                        "variant_id": row.get("variant_id"),
                        metric_name: _round4(_metric(row, metric_name)),
                        "unknown_predictions": _as_int(row.get("unknown_predictions")),
                        "known_negative_hits": _as_int(row.get("known_negative_hits")),
                    }
                    for row in rows
                },
            }
        )
    return sorted(
        summaries,
        key=lambda s: (s["worst_metric"] or -1, s["avg_metric"] or -1),
        reverse=True,
    )


def best_summary(summaries: list[VariantSummary]) -> VariantSummary | None:
    return summaries[0] if summaries else None


# -----------------------------
# diagnostics
# -----------------------------

def _best_candidate_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
    cand = summary.get("best_candidate")
    if isinstance(cand, dict):
        return cand
    accepted = summary.get("accepted")
    if isinstance(accepted, dict) and isinstance(accepted.get("best_candidate"), dict):
        return accepted["best_candidate"]
    return {}


def _dominant_reason(reason_counts: dict[str, int]) -> dict[str, Any] | None:
    if not reason_counts:
        return None
    total = sum(max(0, int(v)) for v in reason_counts.values())
    if total <= 0:
        return None
    reason, count = max(reason_counts.items(), key=lambda kv: kv[1])
    return {"reason": reason, "count": int(count), "share": _round4(count / total)}


def _recommendations(dominant: dict[str, Any] | None, current_best: VariantSummary | None, family_split: list[dict[str, Any]]) -> list[str]:
    recs: list[str] = []
    reason = dominant.get("reason") if dominant else None
    if reason == "ocr_or_vision_layer_miss":
        recs.append(
            "Prioritize OCR/vision-miss rescue before more broad threshold sweeps. The dominant false-negative bucket is upstream of final adjudication."
        )
    elif reason == "fallback_not_selected":
        recs.append(
            "Prioritize fallback selection rescue. The system is seeing possible evidence but not selecting it often enough."
        )
    elif reason == "deterministic_threshold_or_candidate_generation_miss":
        recs.append(
            "Prioritize deterministic candidate provenance and generation gaps. Threshold sweeps should be narrow and source-aware."
        )
    elif reason == "semantic_or_adjudication_layer_miss":
        recs.append(
            "Prioritize adjudication calibration and review routing. Candidate generation appears less dominant than final decision logic."
        )
    else:
        recs.append("Do not run another broad aggressive matrix until the top false-negative bucket is isolated by provenance.")

    if current_best and current_best.worst_metric is not None:
        recs.append(
            f"Use {current_best.variant_id} as the best newly executed comparator, not necessarily the global champion. "
            f"Its worst {current_best.worst_metric:.4f} is the operational baseline for the next targeted experiment."
        )

    if family_split:
        top = family_split[0]
        if top.get("corpus_count", 0) >= 2:
            recs.append(
                f"Inspect split strategy for family '{top['family']}'. Per-corpus best members may differ, so averaged winner selection may be hiding useful routing signals."
            )

    recs.append("Keep p4 as sustained server parallelism unless a separate p3 test beats it on runs/hour.")
    return recs


def build_diagnostics(run_dir: Path, *, target_recall: float | None = None, metric_name: str | None = None) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    run_summary = _read_json(run_dir / "run_summary.json", {}) or {}
    decision_log = _read_jsonl(run_dir / "decision_log.jsonl")
    scorecard_rows = _read_csv(run_dir / "scorecard.csv")

    metric_name = metric_name or str(run_summary.get("target_metric") or "strict_recall")
    target_recall = float(target_recall if target_recall is not None else run_summary.get("target_recall", 0.8))
    iteration_count = _as_int(run_summary.get("iteration_count"), 0) or None

    all_variants = aggregate_variants(
        scorecard_rows,
        metric_name=metric_name,
        current_iteration_count=iteration_count,
        source_filter=None,
    )
    current_variants = aggregate_variants(
        scorecard_rows,
        metric_name=metric_name,
        current_iteration_count=iteration_count,
        source_filter="current_run",
    )
    inherited_variants = aggregate_variants(
        scorecard_rows,
        metric_name=metric_name,
        current_iteration_count=iteration_count,
        source_filter="inherited_or_bootstrap",
    )
    family_split = aggregate_family_by_corpus(
        scorecard_rows,
        metric_name=metric_name,
        current_iteration_count=iteration_count,
    )

    global_best = _best_candidate_from_summary(run_summary)
    best_row = global_best.get("best_row") if isinstance(global_best.get("best_row"), dict) else {}
    global_best_source = source_bucket(best_row, iteration_count) if best_row else "unknown"
    current_best = best_summary(current_variants)
    inherited_best = best_summary(inherited_variants)

    usage = run_summary.get("usage") if isinstance(run_summary.get("usage"), dict) else {}
    total_runtime_seconds = _as_float(usage.get("total_runtime_seconds"), None)
    if total_runtime_seconds is None:
        total_runtime_seconds = _as_float(run_summary.get("total_runtime_seconds"), None)
    executed_runs_from_decisions = sum(_as_int(row.get("iteration_run_count")) for row in decision_log)
    if executed_runs_from_decisions <= 0:
        executed_runs_from_decisions = len([r for r in scorecard_rows if source_bucket(r, iteration_count) == "current_run"])

    runtime_hours = _safe_div(total_runtime_seconds or 0.0, 3600.0)
    throughput = {
        "total_runtime_seconds": _round4(total_runtime_seconds),
        "runtime_hours": _round4(runtime_hours),
        "executed_runs_from_decision_log": executed_runs_from_decisions,
        "seconds_per_executed_run": _round4(_safe_div(total_runtime_seconds or 0.0, executed_runs_from_decisions)),
        "runs_per_hour": _round4(_safe_div(executed_runs_from_decisions, runtime_hours or 0.0)),
        "openai_ocr_attempted_total": _as_int(usage.get("openai_ocr_attempted")),
        "embedding_calls_total": _as_int(usage.get("embedding_calls")),
        "llm_analysis_calls_total": _as_int(usage.get("llm_analysis_calls")),
        "openai_ocr_attempted_per_executed_run": _round4(_safe_div(_as_int(usage.get("openai_ocr_attempted")), executed_runs_from_decisions)),
        "embedding_calls_per_executed_run": _round4(_safe_div(_as_int(usage.get("embedding_calls")), executed_runs_from_decisions)),
    }

    plateau = {
        "stop_reason": run_summary.get("stop_reason"),
        "status": run_summary.get("status"),
        "iteration_count": iteration_count,
        "plateau_count_final": decision_log[-1].get("plateau_count") if decision_log else None,
        "best_metric_gain_by_iteration": [
            {
                "iteration": row.get("iteration"),
                "best_variant_id": row.get("best_variant_id"),
                "best_worst_metric": row.get("best_worst_metric"),
                "best_metric_gain": row.get("best_metric_gain"),
                "plateau_count": row.get("plateau_count"),
                "stop_reason": row.get("stop_reason"),
            }
            for row in decision_log
        ],
    }

    global_reason_counts = {}
    if isinstance(global_best.get("false_negative_reason_counts"), dict):
        global_reason_counts = {str(k): _as_int(v) for k, v in global_best["false_negative_reason_counts"].items()}
    if not global_reason_counts and current_best:
        global_reason_counts = current_best.false_negative_reason_counts
    dominant = _dominant_reason(global_reason_counts)

    target_gap = None
    if global_best.get("worst_metric") is not None:
        target_gap = _round4(target_recall - float(global_best["worst_metric"]))

    current_vs_global = None
    if current_best is not None and global_best.get("worst_metric") is not None:
        current_vs_global = {
            "current_best_variant_id": current_best.variant_id,
            "current_best_worst_metric": current_best.worst_metric,
            "global_best_variant_id": global_best.get("variant_id"),
            "global_best_worst_metric": _round4(float(global_best.get("worst_metric"))),
            "current_minus_global_worst_metric": _round4((current_best.worst_metric or 0.0) - float(global_best.get("worst_metric"))),
            "current_best_avg_metric": current_best.avg_metric,
            "global_best_avg_metric": _round4(_as_float(global_best.get("avg_metric"), 0.0)),
        }

    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "target_metric": metric_name,
        "target_recall": target_recall,
        "target_gap_vs_global_best_worst_metric": target_gap,
        "global_best": global_best,
        "global_best_source": global_best_source,
        "current_best": asdict(current_best) if current_best else None,
        "inherited_best": asdict(inherited_best) if inherited_best else None,
        "current_vs_global": current_vs_global,
        "dominant_false_negative_reason": dominant,
        "false_negative_reason_counts": global_reason_counts,
        "throughput": throughput,
        "plateau": plateau,
        "recommendations": _recommendations(dominant, current_best, family_split),
        "variant_comparison": [asdict(v) for v in all_variants],
        "current_variant_comparison": [asdict(v) for v in current_variants],
        "family_by_corpus": family_split,
    }
    return diagnostics


# -----------------------------
# writing outputs
# -----------------------------

def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_markdown(d: dict[str, Any]) -> str:
    global_best = d.get("global_best") or {}
    current_best = d.get("current_best") or {}
    throughput = d.get("throughput") or {}
    dominant = d.get("dominant_false_negative_reason") or {}
    plateau = d.get("plateau") or {}
    current_vs_global = d.get("current_vs_global") or {}

    lines: list[str] = []
    lines.append("# v0.10.8 Calibration Diagnostics")
    lines.append("")
    lines.append("## Decision readout")
    lines.append("")
    lines.append(f"- Run dir: `{d.get('run_dir')}`")
    lines.append(f"- Target: `{d.get('target_metric')} >= {_fmt(d.get('target_recall'))}`")
    lines.append(f"- Status: `{plateau.get('status')}`")
    lines.append(f"- Stop reason: `{plateau.get('stop_reason')}`")
    lines.append(f"- Global best variant: `{global_best.get('variant_id', 'n/a')}`")
    lines.append(f"- Global best source: `{d.get('global_best_source')}`")
    lines.append(f"- Global best worst metric: `{_fmt(global_best.get('worst_metric'))}`")
    lines.append(f"- Gap to target from global best worst metric: `{_fmt(d.get('target_gap_vs_global_best_worst_metric'))}`")
    lines.append("")
    lines.append("## Newly executed comparator")
    lines.append("")
    if current_best:
        lines.append(f"- Current-run best exact variant: `{current_best.get('variant_id')}`")
        lines.append(f"- Current-run best worst metric: `{_fmt(current_best.get('worst_metric'))}`")
        lines.append(f"- Current-run best avg metric: `{_fmt(current_best.get('avg_metric'))}`")
        lines.append(f"- Current-run best corpora: `{', '.join(current_best.get('corpora') or [])}`")
        lines.append(f"- Current minus global worst metric: `{_fmt(current_vs_global.get('current_minus_global_worst_metric'))}`")
    else:
        lines.append("- No current-run comparator could be identified from scorecard metadata.")
    lines.append("")
    lines.append("## Plateau")
    lines.append("")
    lines.append(f"- Iterations: `{plateau.get('iteration_count')}`")
    lines.append(f"- Final plateau count: `{plateau.get('plateau_count_final')}`")
    for item in plateau.get("best_metric_gain_by_iteration") or []:
        lines.append(
            f"- Iteration `{item.get('iteration')}`: best=`{item.get('best_variant_id')}`, "
            f"worst=`{_fmt(item.get('best_worst_metric'))}`, gain=`{_fmt(item.get('best_metric_gain'))}`, "
            f"plateau=`{item.get('plateau_count')}`"
        )
    lines.append("")
    lines.append("## Throughput")
    lines.append("")
    lines.append(f"- Runtime hours: `{_fmt(throughput.get('runtime_hours'))}`")
    lines.append(f"- Executed runs from decision log: `{throughput.get('executed_runs_from_decision_log')}`")
    lines.append(f"- Runs/hour: `{_fmt(throughput.get('runs_per_hour'))}`")
    lines.append(f"- Seconds/executed run: `{_fmt(throughput.get('seconds_per_executed_run'))}`")
    lines.append(f"- OpenAI OCR attempted/run: `{_fmt(throughput.get('openai_ocr_attempted_per_executed_run'))}`")
    lines.append(f"- Embedding calls/run: `{_fmt(throughput.get('embedding_calls_per_executed_run'))}`")
    lines.append("")
    lines.append("## Bottleneck")
    lines.append("")
    if dominant:
        lines.append(
            f"- Dominant false-negative reason: `{dominant.get('reason')}` "
            f"({dominant.get('count')} hits, share `{_fmt(dominant.get('share'))}`)"
        )
    for reason, count in sorted((d.get("false_negative_reason_counts") or {}).items(), key=lambda kv: kv[1], reverse=True):
        lines.append(f"- `{reason}`: `{count}`")
    lines.append("")
    lines.append("## Recommendations")
    lines.append("")
    for rec in d.get("recommendations") or []:
        lines.append(f"- {rec}")
    lines.append("")
    lines.append("## Top current-run variants")
    lines.append("")
    lines.append("| variant | source | corpora | worst | avg | best | unknown | known negative |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for row in (d.get("current_variant_comparison") or [])[:12]:
        lines.append(
            f"| `{row.get('variant_id')}` | `{row.get('source')}` | {row.get('corpus_count')} | "
            f"{_fmt(row.get('worst_metric'))} | {_fmt(row.get('avg_metric'))} | {_fmt(row.get('best_metric'))} | "
            f"{row.get('total_unknown_predictions')} | {row.get('total_known_negative_hits')} |"
        )
    lines.append("")
    lines.append("## Family/corpus split hints")
    lines.append("")
    lines.append("These are not accepted candidates. They show whether different corpora prefer different members of a logical variant family.")
    lines.append("")
    for item in (d.get("family_by_corpus") or [])[:8]:
        lines.append(
            f"- `{item.get('family')}`: worst=`{_fmt(item.get('worst_metric'))}`, "
            f"avg=`{_fmt(item.get('avg_metric'))}`, best=`{_fmt(item.get('best_metric'))}`"
        )
        corpus_best = item.get("corpus_best") or {}
        for corpus, best in corpus_best.items():
            lines.append(
                f"  - `{corpus}`: `{best.get('variant_id')}` / `{best.get('run_id')}` = "
                f"`{_fmt(best.get(d.get('target_metric') or 'strict_recall'))}`"
            )
    lines.append("")
    return "\n".join(lines)


def write_outputs(diagnostics: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "v0108_diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (out_dir / "v0108_diagnostics.md").write_text(render_markdown(diagnostics), encoding="utf-8")

    variant_fields = [
        "variant_id",
        "family",
        "source",
        "run_count",
        "corpus_count",
        "corpora",
        "worst_metric",
        "avg_metric",
        "best_metric",
        "total_unknown_predictions",
        "total_known_negative_hits",
        "max_candidates_per_100_pages",
        "total_runtime_seconds",
        "total_openai_ocr_attempted",
        "total_embedding_calls",
    ]
    with (out_dir / "variant_comparison.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=variant_fields)
        writer.writeheader()
        for row in diagnostics.get("variant_comparison") or []:
            flat = {k: row.get(k) for k in variant_fields}
            if isinstance(flat.get("corpora"), list):
                flat["corpora"] = ";".join(flat["corpora"])
            writer.writerow(flat)

    with (out_dir / "family_by_corpus.csv").open("w", encoding="utf-8", newline="") as f:
        fields = ["family", "corpus_id", "variant_id", "run_id", diagnostics.get("target_metric") or "strict_recall", "unknown_predictions", "known_negative_hits"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for item in diagnostics.get("family_by_corpus") or []:
            for corpus_id, best in (item.get("corpus_best") or {}).items():
                writer.writerow(
                    {
                        "family": item.get("family"),
                        "corpus_id": corpus_id,
                        "variant_id": best.get("variant_id"),
                        "run_id": best.get("run_id"),
                        diagnostics.get("target_metric") or "strict_recall": best.get(diagnostics.get("target_metric") or "strict_recall"),
                        "unknown_predictions": best.get("unknown_predictions"),
                        "known_negative_hits": best.get("known_negative_hits"),
                    }
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate v0.10.8 calibration diagnostics for a dupe-engine run directory.")
    parser.add_argument("run_dir", type=Path, help="Calibration run directory containing run_summary.json and scorecard.csv")
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory. Defaults to RUN_DIR/v0108_diagnostics")
    parser.add_argument("--target-recall", type=float, default=None, help="Override target recall")
    parser.add_argument("--metric", default=None, help="Override target metric column. Defaults to run_summary target_metric or strict_recall")
    args = parser.parse_args(argv)

    run_dir = args.run_dir
    out_dir = args.out_dir or (run_dir / "v0108_diagnostics")
    diagnostics = build_diagnostics(run_dir, target_recall=args.target_recall, metric_name=args.metric)
    write_outputs(diagnostics, out_dir)
    print(f"v0.10.8 diagnostics written to: {out_dir}")
    print(f"- {out_dir / 'v0108_diagnostics.md'}")
    print(f"- {out_dir / 'v0108_diagnostics.json'}")
    print(f"- {out_dir / 'variant_comparison.csv'}")
    print(f"- {out_dir / 'family_by_corpus.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
