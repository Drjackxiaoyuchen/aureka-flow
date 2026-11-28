"""Reproduce a frozen public reference; disagreements return exit 1, bad inputs 2.

No network requests are made. Raw FCS/WSP inputs remain outside the repository.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import flowkit as fk
import numpy as np

from aureka_flow.engine import AnalysisEngine
from aureka_flow.workflows.core.core import analyze_fcs
from scripts.validate_workspace import compare

MANIFEST = ROOT / "docs/references/flowkit-1.2.3.json"


def verify_artifact(path, expected):
    data = path.read_bytes()
    if len(data) != expected["size_bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
        raise ValueError(f"Frozen reference size/SHA-256 mismatch: {path.name}")
    return data


def binary_reference(data, layout):
    """Independent decoding of this one frozen float32 artifact, not a general FCS reader."""
    count = layout["event_count"] * layout["channel_count"]
    dtype = np.dtype(layout["dtype"])
    if len(data) - layout["data_offset"] != count * dtype.itemsize:
        raise ValueError("Frozen reference binary layout does not cover the complete DATA segment.")
    values = np.frombuffer(data, dtype=dtype, count=count, offset=layout["data_offset"])
    values = values.reshape(layout["event_count"], layout["channel_count"]).astype(np.float64)
    values[:, layout["time_channel_index"]] *= layout["time_step"]
    return values


def compensation_reference(raw, detector_labels, spill):
    """Solve the source-declared mixing equations independently of FlowKit's Matrix."""
    fields = spill.split(",")
    n = int(fields[0])
    labels = fields[1:n + 1]
    if n < 1 or len(set(labels)) != n or len(fields) != 1 + n + n * n:
        raise ValueError("Invalid reference spillover dimensions/detector identities.")
    matrix = np.asarray(fields[n + 1:], dtype=float).reshape(n, n)
    if not np.isfinite(matrix).all():
        raise ValueError("Non-finite reference spillover matrix.")
    indices = [detector_labels.index(label) for label in labels]
    values = raw.copy()
    values[:, indices] = np.linalg.solve(matrix.T, raw[:, indices].T).T
    return values, indices


def count_agreement(summary, expected_rows, selected_sample):
    sources = summary["sources"]
    complete = (expected_rows > 0 and summary["gate_sample_rows"] == expected_rows
                and summary["comparable_rows"] == expected_rows and len(sources) == 1
                and sources[0]["sample"] == selected_sample and sources[0]["root_counts_match"])
    return {"complete_for_selected_scope": bool(complete),
            "exact_count_agreement": bool(complete and summary["exact_count_matches"] == expected_rows)}


def qualify(reference_dir, output):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected_fcs = {name for name in manifest["artifacts"] if name.lower().endswith(".fcs")}
    found_fcs = {path.relative_to(reference_dir).as_posix() for path in (reference_dir / "fcs_files").rglob("*")
                 if path.is_file() and path.suffix.lower() == ".fcs"}
    if found_fcs != expected_fcs:
        raise ValueError("Reference directory must contain only the frozen FCS inputs, with no missing or additional samples.")
    artifacts = {name: verify_artifact(reference_dir / name, expected)
                 for name, expected in manifest["artifacts"].items()}
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose a fresh output directory; existing reports are preserved.")
    name = manifest["selected_sample"]
    data = artifacts["fcs_files/" + name]
    engine = AnalysisEngine()
    info = engine.load(data, name, "Public FCS reference · FlowKit 1.2.3")
    record = engine.record(info["id"])
    reference = binary_reference(data, manifest["binary_layout"])
    raw = engine.events(record, "raw")
    expected, indices = compensation_reference(reference, record.sample.pnn_labels, record.sample.metadata["spillover"])
    comp = engine.events(record, "fcs")
    batch = analyze_fcs(reference_dir / "fcs_files" / name, {
        "schema_version": "yeast-facs-analysis-config/v1", "sample_id": name, "evidence_kind": "user_data",
        "channels": [record.sample.pnn_labels[i] for i in indices],
        "compensation": {"state": "embedded", "reason": "Public-reference arithmetic check; prior processing remains unverified"},
    })["samples"][0]
    checks = {
        "raw_values_and_event_order_exact": bool(np.array_equal(raw, reference)),
        "embedded_matrix_arithmetic_agrees": bool(np.allclose(comp, expected, rtol=1e-12, atol=1e-9)),
        "native_batch_count_and_event_order": batch["selected_count"] == len(reference)
            and batch["processing"]["selected_event_ranges"] == [[0, len(reference)]],
        "native_batch_fluorescence_medians": all(np.isclose(
            batch["channels"][record.sample.pnn_labels[i]]["median"], np.median(expected[:, i]), rtol=1e-12, atol=1e-9)
            for i in indices),
        "source_hash_preserved": info["sha256"] == batch["source"]["sha256"] == manifest["artifacts"]["fcs_files/" + name]["sha256"],
    }
    rows, summary = compare(reference_dir / "8_color_ICS.wsp", reference_dir / "fcs_files", output,
                            include_diagnostics=True)
    # The replay and native adapter reopen files; discard qualification if an
    # artifact changed after the initial immutable-input check.
    for artifact, expected_artifact in manifest["artifacts"].items():
        verify_artifact(reference_dir / artifact, expected_artifact)
    agreement = count_agreement(summary, manifest["expected_gate_rows"], name)
    diagnostic_summary = summary["gate_diagnostics"]
    diagnostic_checks = {
        "all_expected_rectangles_diagnosed": diagnostic_summary["rectangle_gates_diagnosed"] == manifest["expected_rectangle_gates"],
        "literal_rectangle_memberships_agree": diagnostic_summary["rectangle_membership_mismatches"] == 0,
    }
    diagnostics = json.loads((output / diagnostic_summary["filename"]).read_text(encoding="utf-8"))
    first_difference = next((row["gate_path"] for row in rows if row["delta_events"] not in (None, 0)), None)
    first_gate = next((gate for sample in diagnostics["samples"] for gate in sample["gates"]
                       if "/".join(gate["gate_path"]) == first_difference), None)
    report = {
        "schema_version": 1, "evidence_kind": "public_fcs_reference",
        "reference": manifest, "flowkit_version": fk.__version__,
        "software": {**engine.project()["software"], "numpy": np.__version__, "flowio": version("flowio")},
        "code_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in [
            "scripts/qualify_public_reference.py", "scripts/validate_workspace.py", "aureka_flow/engine.py",
            "scripts/workspace_diagnostics.py", "aureka_flow/import_review.py", "aureka_flow/fcs_import.py",
            "aureka_flow/workflows/core/core.py"]},
        "source_reported": info["import_review"]["source_reported"],
        "import_checks": {key: bool(value) for key, value in checks.items()},
        "raw_max_absolute_difference": float(np.max(np.abs(raw - reference))),
        "compensated_max_absolute_difference": float(np.max(np.abs(comp - expected))),
        "flowjo_count_comparison": summary, "count_agreement": agreement,
        "replay_diagnostic_checks": diagnostic_checks,
        "first_count_disagreement_diagnostic": first_gate,
        "replay_diagnostic_scope": diagnostics["scope"],
        "gate_count_comparisons": [{key: row[key] for key in [
            "gate_path", "flowjo_count", "flowkit_count", "delta_events", "flowjo_percent_parent",
            "flowkit_percent_parent", "delta_parent_percentage_points", "relative_count_difference_pct", "status"]}
            for row in rows],
        "max_absolute_relative_count_difference_pct": max(
            (abs(row["relative_count_difference_pct"]) for row in rows if row["relative_count_difference_pct"] is not None), default=None),
        "qualification_passed": bool(all(checks.values()) and all(diagnostic_checks.values())
                                     and agreement["exact_count_agreement"]),
        "scope": "Binary/preprocessing/matrix arithmetic and stored gate-count checks for one frozen file. "
                 "No independent FlowJo event masks, direct FACSDiva export lineage, FACSMelody validation or biological endpoint validation.",
    }
    (output / "qualification.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = qualify(args.reference_dir, args.output)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"import_checks": report["import_checks"], "count_agreement": report["count_agreement"],
                      "qualification_passed": report["qualification_passed"]}))
    return 0 if report["qualification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
