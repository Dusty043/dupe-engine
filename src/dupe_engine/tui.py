from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

PROFILE_CHOICES = [
    "baseline",
    "ocr",
    "ocr-openai-dry-run",
    "ocr-live",
    "embeddings-dry-run",
    "governance",
]

ROUND_CHOICES = ["single", "truth-and-no-truth"]

PROFILE_DESCRIPTIONS = {
    "baseline": "Deterministic-only eval. Best for comparing OCR/AI lift against a cheap baseline.",
    "ocr": "Native text + Tesseract OCR validation. No provider calls.",
    "ocr-openai-dry-run": "Tesseract plus provider vision-OCR selection reporting. No provider calls.",
    "ocr-live": "Tesseract plus live provider vision-OCR fallback when configured. Embeddings stay off.",
    "embeddings-dry-run": "OCR plus embedding-route selection/governance. No embedding provider calls.",
    "governance": "OCR + provider vision-OCR dry-run + embedding dry-run + AI ledger. No provider calls.",
}


@dataclass(frozen=True)
class BenchmarkOptions:
    pdf_dir: Path
    truth_path: Path | None
    output_dir: Path
    dpi: int = 150
    profile: str = "ocr"
    eval_threshold: float = 0.0
    include_text_preview: bool = False
    tesseract_profiles: str | None = None
    truth_autodetect: bool = True

    def normalized(self) -> "BenchmarkOptions":
        profile = self.profile.strip().lower()
        if profile not in PROFILE_CHOICES:
            raise ValueError(f"Unknown benchmark profile: {self.profile}")
        return BenchmarkOptions(
            pdf_dir=self.pdf_dir,
            truth_path=self.truth_path,
            output_dir=self.output_dir,
            dpi=int(self.dpi),
            profile=profile,
            eval_threshold=float(self.eval_threshold),
            include_text_preview=bool(self.include_text_preview),
            tesseract_profiles=self.tesseract_profiles.strip() if isinstance(self.tesseract_profiles, str) and self.tesseract_profiles.strip() else None,
            truth_autodetect=bool(self.truth_autodetect),
        )


def build_benchmark_command(options: BenchmarkOptions) -> list[str]:
    """Build the exact eval-all command used by the benchmark TUI.

    The command intentionally writes every major report family so a benchmark folder can
    be inspected after the run without re-running the engine.
    """
    options = options.normalized()
    out = options.output_dir
    cmd = [
        sys.executable,
        "-m",
        "dupe_engine.cli",
        "eval-all",
        str(options.pdf_dir),
        "--work-dir",
        str(out / "work"),
        "--out",
        str(out / "results.json"),
        "--eval-out",
        str(out / "eval.json"),
        "--csv",
        str(out / "matches.csv"),
        "--html",
        str(out / "review.html"),
        "--pages-out",
        str(out / "pages.json"),
        "--calibration-out",
        str(out / "calibration.json"),
        "--candidate-summary-csv",
        str(out / "candidate_summary.csv"),
        "--false-positive-csv",
        str(out / "false_positive_review.csv"),
        "--false-negative-csv",
        str(out / "false_negative_review.csv"),
        "--threshold-sweep-csv",
        str(out / "threshold_sweep.csv"),
        "--ocr-validation-out",
        str(out / "ocr_validation.json"),
        "--ocr-route-csv",
        str(out / "ocr_route.csv"),
        "--ocr-candidate-csv",
        str(out / "ocr_candidate.csv"),
        "--ai-ledger-out",
        str(out / "ai_ledger.json"),
        "--ai-ledger-csv",
        str(out / "ai_ledger.csv"),
        "--dpi",
        str(options.dpi),
        "--eval-threshold",
        str(options.eval_threshold),
    ]
    if options.truth_path:
        cmd.extend(["--truth", str(options.truth_path)])
    elif not options.truth_autodetect:
        cmd.append("--no-truth-autodetect")
    if options.tesseract_profiles:
        cmd.extend(["--tesseract-profiles", options.tesseract_profiles])

    if options.profile in {"ocr", "ocr-openai-dry-run", "ocr-live", "embeddings-dry-run", "governance"}:
        cmd.append("--ocr")
    if options.profile in {"ocr-openai-dry-run", "governance"}:
        cmd.extend(["--openai-ocr", "--openai-ocr-dry-run"])
    if options.profile == "ocr-live":
        cmd.extend(["--openai-ocr", "--openai-ocr-live"])
    if options.profile in {"embeddings-dry-run", "governance"}:
        cmd.extend(["--embeddings", "--embedding-dry-run"])
    if options.include_text_preview:
        cmd.append("--include-text-preview")
    return cmd


def build_truth_and_no_truth_rounds(options: BenchmarkOptions) -> list[tuple[str, list[str], Path]]:
    """Build paired benchmark rounds for synthetic-vs-production comparison.

    The first round keeps explicit/auto-detected truth enabled. The second round
    intentionally disables truth auto-detection so it behaves like a production
    batch even when a truth file sits next to the corpus.
    """
    options = options.normalized()
    with_truth = replace(
        options,
        output_dir=options.output_dir / "with_truth",
        truth_autodetect=True,
    )
    no_truth = replace(
        options,
        truth_path=None,
        output_dir=options.output_dir / "no_truth",
        truth_autodetect=False,
    )
    return [
        ("with_truth", build_benchmark_command(with_truth), with_truth.output_dir),
        ("no_truth", build_benchmark_command(no_truth), no_truth.output_dir),
    ]


def quote_command(command: Iterable[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def run_tui(args: Any) -> None:
    """Entry point for the dependency-free terminal UI."""
    if getattr(args, "summarize", None):
        print_dashboard(Path(args.summarize))
        return

    if getattr(args, "print_command", False) or getattr(args, "run", False):
        options = options_from_args(args)
        rounds = str(getattr(args, "rounds", "single") or "single")
        if rounds == "truth-and-no-truth":
            commands = build_truth_and_no_truth_rounds(options)
            if getattr(args, "print_command", False):
                for label, command, _output_dir in commands:
                    print(f"# {label}")
                    print(quote_command(command))
            if getattr(args, "run", False):
                for label, command, output_dir in commands:
                    print_header(f"Benchmark round: {label}")
                    code = run_benchmark_command(command, output_dir)
                    if code != 0:
                        raise SystemExit(code)
            return

        command = build_benchmark_command(options)
        if getattr(args, "print_command", False):
            print(quote_command(command))
        if getattr(args, "run", False):
            code = run_benchmark_command(command, options.output_dir)
            if code != 0:
                raise SystemExit(code)
        return

    interactive_loop(args)


def options_from_args(args: Any) -> BenchmarkOptions:
    pdf_dir = getattr(args, "pdf_dir", None)
    truth_path = getattr(args, "truth", None)
    if not pdf_dir:
        raise SystemExit("--pdf-dir is required with --run or --print-command. --truth is optional and auto-detected when omitted.")
    output_dir = Path(getattr(args, "output_dir", None) or default_output_dir())
    return BenchmarkOptions(
        pdf_dir=Path(pdf_dir),
        truth_path=Path(truth_path) if truth_path else None,
        output_dir=output_dir,
        dpi=int(getattr(args, "dpi", 150) or 150),
        profile=str(getattr(args, "profile", "ocr") or "ocr"),
        eval_threshold=float(getattr(args, "eval_threshold", 0.0) or 0.0),
        include_text_preview=bool(getattr(args, "include_text_preview", False)),
        tesseract_profiles=getattr(args, "tesseract_profiles", None),
        truth_autodetect=not bool(getattr(args, "no_truth_autodetect", False)),
    )


def interactive_loop(args: Any) -> None:
    while True:
        clear_screen()
        print_header("Dupe Engine Benchmark TUI")
        print("1) Run benchmark")
        print("2) View existing benchmark folder")
        print("3) Print benchmark command")
        print("4) Show capability doctor")
        print("q) Quit")
        choice = input("\nChoose: ").strip().lower()
        if choice == "1":
            options = prompt_benchmark_options(args)
            command = build_benchmark_command(options)
            print("\nCommand:")
            print(quote_command(command))
            confirm = input("\nRun this benchmark now? [Y/n]: ").strip().lower()
            if confirm in {"", "y", "yes"}:
                run_benchmark_command(command, options.output_dir)
        elif choice == "2":
            folder = input("Benchmark output folder: ").strip()
            if folder:
                print_dashboard(Path(folder))
                pause()
        elif choice == "3":
            options = prompt_benchmark_options(args)
            print("\nCommand:")
            print(quote_command(build_benchmark_command(options)))
            pause()
        elif choice == "4":
            run_doctor()
            pause()
        elif choice in {"q", "quit", "exit"}:
            return
        else:
            print("Unknown choice.")
            pause()


def prompt_benchmark_options(args: Any) -> BenchmarkOptions:
    print_header("Benchmark setup")
    default_pdf = str(getattr(args, "pdf_dir", None) or "")
    default_truth = str(getattr(args, "truth", None) or "")
    default_out = str(getattr(args, "output_dir", None) or default_output_dir())
    default_dpi = str(getattr(args, "dpi", 150) or 150)
    default_profile = str(getattr(args, "profile", "ocr") or "ocr")
    default_tess_profiles = str(getattr(args, "tesseract_profiles", None) or "")
    default_truth_autodetect = not bool(getattr(args, "no_truth_autodetect", False))

    pdf_dir = prompt_path("PDF corpus folder", default_pdf)
    truth = prompt_optional_path("Ground truth JSON; blank auto-detects/skips", default_truth)
    output_dir = prompt_path("Output folder", default_out)
    dpi = int(prompt_value("DPI", default_dpi))
    tesseract_profiles = prompt_value("Tesseract profiles override; blank uses config/env", default_tess_profiles).strip() or None

    print("\nProfiles:")
    for name in PROFILE_CHOICES:
        print(f"- {name}: {PROFILE_DESCRIPTIONS[name]}")
    profile = prompt_value("Profile", default_profile).strip().lower()
    truth_autodetect = default_truth_autodetect
    if not truth:
        truth_autodetect = prompt_value("Auto-detect nearby truth when no truth path is provided? [Y/n]", "y").lower() not in {"n", "no"}
    include_text = prompt_value("Include text previews? Use no for PHI. [y/N]", "n").lower() in {"y", "yes"}
    return BenchmarkOptions(
        pdf_dir=Path(pdf_dir),
        truth_path=Path(truth) if truth else None,
        output_dir=Path(output_dir),
        dpi=dpi,
        profile=profile,
        include_text_preview=include_text,
        tesseract_profiles=tesseract_profiles,
        truth_autodetect=truth_autodetect,
    ).normalized()


def prompt_optional_path(label: str, default: str) -> str:
    return prompt_value(label, default).strip()


def prompt_path(label: str, default: str) -> str:
    value = prompt_value(label, default)
    while not value:
        print(f"{label} is required.")
        value = prompt_value(label, default)
    return value


def prompt_value(label: str, default: str) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def run_benchmark_command(command: list[str], output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_run_metadata(output_dir, command)
    print_header("Benchmark running")
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
    code = process.wait()
    print("\n" + ("Benchmark completed." if code == 0 else f"Benchmark failed with exit code {code}."))
    print_dashboard(output_dir)
    return code


def run_doctor() -> int:
    command = [
        sys.executable,
        "-m",
        "dupe_engine.cli",
        "doctor",
        "--ocr",
        "--openai-ocr",
        "--openai-ocr-dry-run",
        "--embeddings",
    ]
    print_header("Capability doctor")
    return subprocess.call(command)


def write_run_metadata(output_dir: Path, command: list[str]) -> None:
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "command": command,
        "command_string": quote_command(command),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "benchmark_command.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def default_output_dir() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"output/benchmarks/{stamp}"


def print_dashboard(output_dir: Path) -> None:
    summary = collect_dashboard_summary(output_dir)
    print_header(f"Benchmark dashboard: {output_dir}")
    if summary["missing_all"]:
        print("No recognized benchmark outputs found yet.")
        return

    print_section("Run")
    run = summary.get("run", {})
    print_kv("pages", run.get("total_pages"))
    print_kv("matches", run.get("match_count"))
    print_kv("ocr pages", run.get("ocr_pages"))
    print_kv("text sources", run.get("text_source_counts"))
    print_kv("ai ledger records", run.get("ai_call_record_count"))

    print_section("Evaluation")
    truth_status = summary.get("truth_status", {})
    if truth_status:
        print_kv("truth status", truth_status.get("status"))
        print_kv("truth source", truth_status.get("source"))
        print_kv("truth path", truth_status.get("path"))
    if summary.get("evaluation_available") is False:
        print_kv("metrics", "skipped; no pair-level truth")
    eval_summary = summary.get("evaluation", {})
    print_kv("true positives", eval_summary.get("true_positive_count"))
    print_kv("false negatives", eval_summary.get("false_negative_count"))
    print_kv("expected negative hits", eval_summary.get("expected_negative_hit_count"))
    print_kv("partial overlap hits", eval_summary.get("partial_overlap_hit_count"))
    print_kv("recall on must_match", eval_summary.get("recall_on_must_match"))

    print_section("Calibration / reviewability")
    calibration = summary.get("calibration", {})
    print_kv("raw candidates per 100 pages", calibration.get("candidate_pairs_per_100_pages"))
    print_kv("main list candidates", calibration.get("main_review_list_candidate_count"))
    print_kv("main list per 100 pages", calibration.get("main_review_list_pairs_per_100_pages"))
    print_kv("main list recall", calibration.get("main_review_recall_on_must_match"))
    print_kv("known review risk", calibration.get("known_review_risk_count"))

    print_section("OCR")
    ocr = summary.get("ocr", {})
    print_kv("weak/missing native pages", ocr.get("native_weak_or_missing_pages"))
    print_kv("Tesseract attempted/usable/improved", join_counts(ocr, ["tesseract_attempted_pages", "tesseract_usable_pages", "tesseract_improved_pages"]))
    print_kv("vision OCR selected/attempted/usable", join_counts(ocr, ["openai_ocr_selected_pages", "openai_ocr_attempted_pages", "openai_ocr_usable_pages"]))
    print_kv("OCR-dependent recall", ocr.get("truth_ocr_dependent_recall"))

    print_section("AI route governance")
    ai = summary.get("ai_ledger", {})
    print_kv("records", ai.get("record_count"))
    print_kv("selected/attempted/succeeded", join_counts(ai, ["selected_count", "attempted_count", "succeeded_count"]))
    print_kv("dry runs", ai.get("dry_run_count"))
    print_kv("by route", ai.get("by_route"))

    print_section("Artifacts")
    for name, exists in summary.get("artifacts", {}).items():
        if exists:
            print(f"- {name}: {output_dir / name}")


def collect_dashboard_summary(output_dir: Path) -> dict[str, Any]:
    results = load_json_optional(output_dir / "results.json")
    eval_report = load_json_optional(output_dir / "eval.json")
    calibration = load_json_optional(output_dir / "calibration.json")
    ocr = load_json_optional(output_dir / "ocr_validation.json")
    ai = load_json_optional(output_dir / "ai_ledger.json")
    truth_status = (results or {}).get("truth_status") or (eval_report or {}).get("truth_status") or (calibration or {}).get("truth_status")
    artifacts = {
        "results.json": (output_dir / "results.json").exists(),
        "eval.json": (output_dir / "eval.json").exists(),
        "calibration.json": (output_dir / "calibration.json").exists(),
        "ocr_validation.json": (output_dir / "ocr_validation.json").exists(),
        "ai_ledger.json": (output_dir / "ai_ledger.json").exists(),
        "review.html": (output_dir / "review.html").exists(),
        "matches.csv": (output_dir / "matches.csv").exists(),
        "candidate_summary.csv": (output_dir / "candidate_summary.csv").exists(),
        "ocr_route.csv": (output_dir / "ocr_route.csv").exists(),
        "ai_ledger.csv": (output_dir / "ai_ledger.csv").exists(),
    }
    return {
        "missing_all": not any(artifacts.values()),
        "run": (results or {}).get("summary", {}),
        "truth_status": truth_status or {},
        "evaluation_available": (eval_report or {}).get("evaluation_available"),
        "evaluation": (eval_report or {}).get("summary", {}),
        "calibration": (calibration or {}).get("summary", {}),
        "ocr": (ocr or {}).get("summary", {}),
        "ai_ledger": (ai or {}).get("summary", {}),
        "artifacts": artifacts,
    }


def load_json_optional(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def join_counts(mapping: dict[str, Any], keys: list[str]) -> str | None:
    values = [mapping.get(key) for key in keys]
    if all(value is None for value in values):
        return None
    return "/".join("-" if value is None else str(value) for value in values)


def print_header(title: str) -> None:
    width = 78
    print("=" * width)
    print(title)
    print("=" * width)


def print_section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def print_kv(label: str, value: Any) -> None:
    if value is None or value == {}:
        value = "-"
    print(f"{label:34} {value}")


def clear_screen() -> None:
    print("\033[2J\033[H", end="")


def pause() -> None:
    input("\nPress Enter to continue...")
