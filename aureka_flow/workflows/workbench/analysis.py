"""Join explicit metadata and compute descriptive bookkeeping only."""

from aureka_flow import __version__

from collections import defaultdict
from copy import deepcopy

from . import validation as v


def analyze(measurements, manifest):
    measured = v.measurements(measurements)
    declared = v.manifest(manifest)
    if manifest.get("evidence_kind", measurements["evidence_kind"]) != measurements["evidence_kind"]:
        v.fail("manifest.evidence_kind", "does not match measurements.evidence_kind")
    measured_ids = {sample["sample_id"] for sample in measured}
    declared_ids = {sample["sample_id"] for sample in declared}
    if measured_ids != declared_ids:
        v.fail("sample_id join", f"missing manifest IDs={sorted(measured_ids - declared_ids)!r}; unmatched manifest IDs={sorted(declared_ids - measured_ids)!r}")
    metadata = {sample["sample_id"]: sample for sample in declared}
    joined = []
    warnings = []

    def warn(code, message, sample_ids=None):
        item = {"code": code, "message": message}
        if sample_ids:
            item["sample_ids"] = sample_ids
        warnings.append(item)

    for sample in measured:
        details = metadata[sample["sample_id"]]
        collisions = (set(sample) & set(details)) - {"sample_id"}
        if collisions:
            v.fail(f"measurements.sample[{sample['sample_id']!r}]", f"manifest field collision: {sorted(collisions)!r}")
        merged = deepcopy(sample)
        merged.update(deepcopy(details))
        joined.append(merged)
        sample_id = sample["sample_id"]
        if sample["selected_count"] == 0:
            warn("zero_selected_events", "No selected events; marker medians are unavailable.", [sample_id])
        if not sample["channels"]:
            warn("no_channels", "No detector summaries were supplied.", [sample_id])
        for detector, summary in sample["channels"].items():
            if summary["finite_count"] != sample["selected_count"]:
                warn("finite_denominator_differs", f"Detector {detector}: median uses {summary['finite_count']} finite values out of {sample['selected_count']} selected events.", [sample_id])
        if sample["qc_flags"]:
            warn("upstream_qc_flags", "Upstream QC flags are preserved and have not been resolved by this report.", [sample_id])

    missing_bio = [s["sample_id"] for s in joined if s["biological_replicate"] is None]
    missing_batch = [s["sample_id"] for s in joined if s["batch_id"] is None]
    if missing_bio:
        warn("missing_biological_replicate", "Missing biological replicate identities remain unknown; files/events are not biological replicates.", missing_bio)
    if missing_batch:
        warn("missing_batch", "Batch identity is missing; cross-sample comparability cannot be established.", missing_batch)
    batches = sorted({s["batch_id"] for s in joined if s["batch_id"] is not None})
    if len(batches) > 1:
        warn("cross_batch_blocked", "Multiple batches are present. Version 1 accepts no validated calibration evidence, so biological cross-batch comparison is blocked. Reference labels alone do not calibrate; no normalization is applied.")
    biological_acquisitions = defaultdict(list)
    conditions = defaultdict(list)
    for sample in joined:
        conditions[sample["condition"]].append(sample)
        if sample["biological_replicate"] is not None:
            biological_acquisitions[(sample["condition"], sample["biological_replicate"])].append(sample["sample_id"])
    for (condition, replicate), samples in biological_acquisitions.items():
        if len(samples) > 1:
            warn("repeated_biological_identity", f"Condition {condition!r}, biological replicate {replicate!r} appears in multiple sample records. These records do not add independent biological replicates.", samples)
    condition_summaries = []
    insufficient_biology = False
    for condition, samples in sorted(conditions.items()):
        bio_ids = sorted({s["biological_replicate"] for s in samples if s["biological_replicate"] is not None})
        if len(bio_ids) < 2:
            insufficient_biology = True
            warn("insufficient_biological_replicates", f"Condition {condition!r} has {len(bio_ids)} distinct declared biological replicate identities; event counts do not increase that count.", [s["sample_id"] for s in samples])
        condition_summaries.append({"condition": condition, "sample_record_count": len(samples), "declared_biological_replicate_count": len(bio_ids), "biological_replicate_ids": bio_ids, "batch_ids": sorted({s["batch_id"] for s in samples if s["batch_id"] is not None}), "missing_biological_replicate_count": sum(s["biological_replicate"] is None for s in samples)})
    if len(conditions) > 1 and len(batches) > 1:
        by_condition = [{s["batch_id"] for s in samples} for samples in conditions.values()]
        if not set.intersection(*by_condition):
            warn("condition_batch_confounding", "No batch spans all conditions. Condition and batch effects cannot be separated from these summaries.")
    signatures = {str(sorted(s["channels"])) for s in joined}
    if len(signatures) > 1:
        warn("channel_sets_differ", "Sample detector sets differ; missing markers are not zero fluorescence.")
    # Different processing settings may encode distinct compensation, transforms,
    # or gates; equality is not proof of biological comparability.
    import json
    if len({json.dumps(s["processing"], sort_keys=True, allow_nan=False) for s in joined}) > 1:
        warn("processing_differs", "Processing metadata differs across samples. No correction or equivalence is inferred.")
    if len({s["gate_status"] for s in joined}) > 1:
        warn("gate_status_differs", "Samples have different gate-status labels; their selected populations may differ.")
    if len(batches) > 1:
        comparison_status = "cross_batch_blocked"
    elif missing_batch or missing_bio or insufficient_biology:
        comparison_status = "metadata_limited"
    else:
        comparison_status = "exploratory_only"
    return {
        "schema_version": "yeast-facs-experiment/v1",
        "evidence_kind": measurements["evidence_kind"],
        "producer": {"name": "aureka-flow", "version": __version__, "component": "workbench"},
        "samples": joined,
        "warnings": warnings,
        "comparison_status": comparison_status,
        "summary": {
            "sample_record_count": len(joined),
            "condition_count": len(conditions),
            "known_batch_count": len(batches),
            "acquired_event_count_sum": sum(s["event_count"] for s in joined),
            "selected_event_count_sum": sum(s["selected_count"] for s in joined),
            "count_scope": "Sums of acquisition records, not counts of independent biological replicates or unique organisms.",
        },
        "condition_summaries": condition_summaries,
        "measurement_metadata": deepcopy({k: val for k, val in measurements.items() if k not in ("schema_version", "evidence_kind", "samples")}),
        "manifest_metadata": deepcopy({k: val for k, val in manifest.items() if k not in ("schema_version", "samples")}),
        "limits": [
            "Software alpha; descriptive supplied summaries, not biological validation.",
            "No gating, reprocessing, batch normalization, significance testing or affinity estimation is performed.",
            "Selected events are not assumed to be live, single, expressing or binding cells.",
            "Each channel median describes only its finite_count values among selected_count selected events; missing or non-finite values are not zero.",
            "Detector names and numeric medians alone do not establish common units, calibration, marker identity or comparable gate populations.",
            "Biological replicate identities and control roles are user declarations, not independently verified evidence.",
        ],
    }


def synthetic_manifest(measurements):
    samples = v.measurements(measurements)
    if measurements["evidence_kind"] != "synthetic":
        v.fail("measurements.evidence_kind", "demo manifest creation is allowed only for synthetic evidence")
    # These intentionally invented labels illustrate a join, not reconstruction
    # of any underlying experiment. Biological identities are left unknown.
    return {
        "schema_version": "yeast-facs-samples/v1",
        "evidence_kind": "synthetic",
        "description": "SYNTHETIC DEMO ONLY: invented display metadata; no real sample identities or biological replicate independence inferred.",
        "samples": [
            {"sample_id": sample["sample_id"], "condition": "synthetic-demo", "biological_replicate": None, "batch_id": "synthetic-demo-batch", "plate": None, "well": None, "control_role": "sample"}
            for sample in samples
        ],
    }
