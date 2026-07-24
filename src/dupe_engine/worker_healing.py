"""Automatic post-job healing for the AWS worker.

Diagnoses every completed job in-process and verifies a prescribed config
fix, without needing a human to run `dupe-engine heal` by hand or reviewer
feedback to exist yet (recall/precision-based issues still require truth or
feedback data and won't fire in production; queue-load and OCR-coverage
issues need neither and are what this will realistically catch).

This only ever writes a heal_output/ artifact alongside the job's normal run
artifacts — it never changes what a reviewer sees. If a healed re-run scores
better, that's a signal for someone to review and decide whether to change
defaults, not something applied automatically to a live reviewer-facing job.
The CLI's own `--apply` never mutates the original run in place either — it
writes a sibling `healed/` directory — so this matches that behavior rather
than introducing a new one.
"""
from __future__ import annotations

import argparse
from dataclasses import fields, replace
from pathlib import Path

from .capabilities import build_capability_report
from .config import EngineConfig
from .engine import run_ab_compare
from .heal_prescriber import build_prescription
from .healing_harness import (
    _certification_to_dict,
    _prescription_to_dict,
    assess_run,
    certify,
    compare_runs,
    diagnose_run,
)
from .log import log, log_exception
from .reporting import build_report, write_json


def run_post_job_heal(
    *,
    job_id: str,
    workdir: Path,
    run_dir: Path,
    received_dir: Path,
    ere_dir: Path,
    config: EngineConfig,
) -> None:
    """Best-effort: diagnose the just-completed job and verify a fix in-process.

    Never raises — a healing failure must never affect the job's own success.
    """
    try:
        _run_post_job_heal_inner(
            job_id=job_id, workdir=workdir, run_dir=run_dir,
            received_dir=received_dir, ere_dir=ere_dir, config=config,
        )
    except Exception as exc:
        log_exception("warn", "heal_failed", exc, job_id=job_id)


def _run_post_job_heal_inner(
    *,
    job_id: str,
    workdir: Path,
    run_dir: Path,
    received_dir: Path,
    ere_dir: Path,
    config: EngineConfig,
) -> None:
    heal_out = run_dir / "heal_output"
    heal_out.mkdir(parents=True, exist_ok=True)

    assessment = assess_run(workdir)
    diagnosis = diagnose_run(assessment)
    prescription = build_prescription(diagnosis)
    write_json(heal_out / "prescription.json", _prescription_to_dict(prescription))

    log(
        "info", "heal_assessed", job_id=job_id,
        health_score=assessment.health_score,
        issues=[i.root_cause for i in diagnosis.issues],
    )

    if not prescription.cli_args:
        log("info", "heal_skipped_no_issues", job_id=job_id, health_score=assessment.health_score)
        return

    healed_config = _apply_prescription(config, prescription.cli_args)

    healed_workdir = heal_out / "healed"
    healed_workdir.mkdir(parents=True, exist_ok=True)
    log("info", "heal_apply_start", job_id=job_id, cli_args=prescription.cli_args)

    h_pages_a, h_pages_b, h_matches = run_ab_compare(
        received_dir, ere_dir, healed_workdir / "work", healed_config,
    )
    h_capabilities = build_capability_report(healed_config, used_core_layers=True)
    h_report = build_report(
        h_pages_a, h_pages_b, h_matches, healed_config, mode="ab", capabilities=h_capabilities,
    )
    write_json(healed_workdir / "results.json", h_report)

    healed_assessment = assess_run(healed_workdir)
    comparison = compare_runs(assessment, healed_assessment)
    certification = certify(comparison)
    write_json(heal_out / "heal_report.json", _certification_to_dict(certification))

    log(
        "info", "heal_certified", job_id=job_id,
        status=certification.status, health_delta=comparison.health_delta,
    )


def _apply_prescription(original: EngineConfig, cli_args: list[str]) -> EngineConfig:
    """Layer a prescription's CLI-flag deltas onto the job's own config.

    Prescriptions are expressed as CLI flags (built for `dupe-engine heal
    --apply`, which shells out to a fresh CLI invocation). The worker builds
    its EngineConfig from env + per-job SQS overrides instead, so this
    replays the flags through the same `cli.build_config` the CLI itself
    uses, diffs the result against an env-only baseline to isolate just the
    prescription's effect, and re-applies only that diff to the job's actual
    config — preserving whatever per-job overrides the original request had.
    """
    from . import cli as cli_module

    parser = argparse.ArgumentParser()
    cli_module.add_common_engine_args(parser)
    parsed = parser.parse_args(cli_args)

    env_base = EngineConfig.from_env()
    healed_env = cli_module.build_config(parsed)

    delta = {
        f.name: getattr(healed_env, f.name)
        for f in fields(EngineConfig)
        if getattr(healed_env, f.name) != getattr(env_base, f.name)
    }
    return replace(original, **delta) if delta else original
