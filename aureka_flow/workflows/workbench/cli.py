"""Local, fresh-output-only CLI."""

import argparse
import json
from pathlib import Path
import sys

from .analysis import analyze, synthetic_manifest
from .report import render_report
from .validation import ValidationError, read_json


def write_output(output, experiment, manifest=None):
    path = Path(output)
    # is_symlink includes dangling symlinks. No --force mode exists in v0.1.
    if path.exists() or path.is_symlink():
        raise ValidationError("output: must be a fresh, nonexistent directory; overwrite is never allowed")
    report = render_report(experiment)
    serialized = json.dumps(experiment, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    synthetic = None if manifest is None else json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    path.mkdir(parents=True, exist_ok=False)
    with (path / "experiment.json").open("x", encoding="utf-8") as handle:
        handle.write(serialized)
    with (path / "report.html").open("x", encoding="utf-8") as handle:
        handle.write(report)
    if synthetic is not None:
        with (path / "synthetic-manifest.json").open("x", encoding="utf-8") as handle:
            handle.write(synthetic)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Join explicit FACS sample metadata and create descriptive local reports. No gating, significance tests, normalization or affinity inference.")
    sub = parser.add_subparsers(dest="command", required=True)
    analysis = sub.add_parser("analyze", help="join measurements and an explicit sample manifest")
    analysis.add_argument("--measurements", required=True)
    analysis.add_argument("--manifest", required=True)
    analysis.add_argument("--output", required=True, help="fresh output directory only")
    demo = sub.add_parser("demo", help="create artificial display metadata for synthetic measurements only")
    demo.add_argument("--measurements", required=True)
    demo.add_argument("--output", required=True, help="fresh output directory only")
    args = parser.parse_args(argv)
    try:
        measurements = read_json(args.measurements)
        manifest = synthetic_manifest(measurements) if args.command == "demo" else read_json(args.manifest)
        experiment = analyze(measurements, manifest)
        output = write_output(args.output, experiment, manifest if args.command == "demo" else None)
    except (ValidationError, OSError, RecursionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"Wrote {output / 'experiment.json'} and {output / 'report.html'}")
    print(f"Evidence: {experiment['evidence_kind']}; comparison_status: {experiment['comparison_status']}; warnings: {len(experiment['warnings'])}")
    return 0
