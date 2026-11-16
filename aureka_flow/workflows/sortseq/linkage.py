"""Validate explicit identities before calculating descriptive read fractions.

No upstream implementations or experimental data are bundled in this module.
"""
from __future__ import annotations

from collections import Counter
import math


class ValidationError(ValueError):
    """An input cannot support an unambiguous descriptive linkage."""


def obj(value, field):
    if not isinstance(value, dict):
        raise ValidationError(f"{field} must be an object")
    return value


def ident(value, field):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValidationError(f"{field} must be a nonempty, trimmed string")
    return value


def integer(value, field, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValidationError(f"{field} must be an integer >= {minimum}")
    return value


def finite_tree(value, field="input"):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValidationError(f"{field} contains a non-finite number")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError(f"{field} object keys must be strings")
            finite_tree(item, f"{field}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            finite_tree(item, f"{field}[{i}]")


def document(value, version, row_key, field):
    obj(value, field)
    finite_tree(value, field)
    if value.get("schema_version") != version:
        raise ValidationError(f"{field}.schema_version must be {version}")
    if value.get("evidence_kind") not in {"synthetic", "user_data"}:
        raise ValidationError(f"{field}.evidence_kind must be synthetic or user_data")
    rows = value.get(row_key)
    if not isinstance(rows, list):
        raise ValidationError(f"{field}.{row_key} must be an array")
    for i, row in enumerate(rows):
        obj(row, f"{field}.{row_key}[{i}]")
    return rows


def samples_by_id(experiment):
    rows = document(experiment, "yeast-facs-experiment/v1", "samples", "experiment")
    if not rows:
        raise ValidationError("experiment.samples must not be empty")
    samples = {}
    for i, row in enumerate(rows):
        field = f"experiment.samples[{i}]"
        sid = ident(row.get("sample_id"), field+".sample_id")
        if sid in samples:
            raise ValidationError(f"duplicate sample_id: {sid}")
        acquired = integer(row.get("event_count"), field+".event_count")
        selected = integer(row.get("selected_count"), field+".selected_count")
        if selected > acquired:
            raise ValidationError(f"{field}.selected_count exceeds event_count")
        if row.get("gate_status") not in {"ungated", "exploratory", "user_supplied_unvalidated"}:
            raise ValidationError(f"{field}.gate_status is unsupported")
        obj(row.get("processing"), field+".processing")
        channels = obj(row.get("channels"), field+".channels")
        for channel, stats in channels.items():
            ident(channel, field+".channel_name")
            obj(stats, field+f".channels.{channel}")
            count = integer(stats.get("finite_count"), field+f".channels.{channel}.finite_count")
            if count > selected:
                raise ValidationError(f"{field}.channels.{channel}.finite_count exceeds selected_count")
            median = stats.get("median")
            if count == 0 and median is not None:
                raise ValidationError(f"{field}.channels.{channel}.median must be null when finite_count=0")
            if count and (type(median) not in (float, int) or not math.isfinite(median)):
                raise ValidationError(f"{field}.channels.{channel}.median must be finite")
        qc = row.get("qc_flags")
        if not isinstance(qc, list) or any(not isinstance(x, str) for x in qc):
            raise ValidationError(f"{field}.qc_flags must be a string array")
        samples[sid] = row
    warnings = experiment.get("warnings")
    if not isinstance(warnings, list):
        raise ValidationError("experiment.warnings must be an array")
    ident(experiment.get("comparison_status"), "experiment.comparison_status")
    return samples


def link_experiment(experiment, sort_bins, variant_counts, min_reads=10):
    """Return explicit joins and within-sequencing-sample fractions, not affinity.

    Rows not supplied for a bin remain missing. Explicit zero counts remain zero.
    A sequencing sample can map to exactly one bin; several bins may reference
    the same acquired FCS sample. Sorted-event counters are not equated to the
    recorded-event count of a diagnostic FCS acquisition.
    """
    integer(min_reads, "min_reads", minimum=1)
    samples = samples_by_id(experiment)
    bins = document(sort_bins, "yeast-sort-bins/v1", "bins", "sort_bins")
    counts = document(variant_counts, "yeast-variant-counts/v1", "counts", "variant_counts")
    if not bins:
        raise ValidationError("sort_bins.bins must not be empty")
    kinds = {x["evidence_kind"] for x in (experiment, sort_bins, variant_counts)}
    if len(kinds) != 1:
        raise ValidationError("evidence_kind must agree across all three inputs")
    by_seq, bin_ids = {}, set()
    for i, row in enumerate(bins):
        p = f"sort_bins.bins[{i}]"
        bid = ident(row.get("bin_id"), p+".bin_id")
        sid = ident(row.get("sample_id"), p+".sample_id")
        seq = ident(row.get("sequencing_sample_id"), p+".sequencing_sample_id")
        ident(row.get("gate_definition_id"), p+".gate_definition_id")
        integer(row.get("sorted_events"), p+".sorted_events")
        if bid in bin_ids:
            raise ValidationError(f"duplicate bin_id: {bid}")
        if seq in by_seq:
            raise ValidationError(f"sequencing_sample_id maps to multiple bins: {seq}")
        if sid not in samples:
            raise ValidationError(f"sort bin references unknown sample_id: {sid}")
        bin_ids.add(bid); by_seq[seq] = row
    unique_keys, totals, row_counts, variants = set(), Counter(), Counter(), set()
    for i, row in enumerate(counts):
        p = f"variant_counts.counts[{i}]"
        seq = ident(row.get("sequencing_sample_id"), p+".sequencing_sample_id")
        variant = ident(row.get("variant_id"), p+".variant_id")
        n = integer(row.get("read_count"), p+".read_count")
        if seq not in by_seq:
            raise ValidationError(f"counts reference unknown sequencing_sample_id: {seq}")
        if (seq, variant) in unique_keys:
            raise ValidationError(f"duplicate count key: {seq} / {variant}")
        unique_keys.add((seq,variant)); totals[seq]+=n; row_counts[seq]+=1; variants.add(variant)
    warnings = ["Descriptive linkage only: no affinity, enrichment or biological significance is inferred.",
                "Reads, sorted events and acquired FCS events are different denominators.",
                "Absent count rows are missing evidence, not proof that a variant is absent."]
    if experiment["comparison_status"] != "exploratory_only":
        warnings.append("Upstream comparison restrictions retained: " + experiment["comparison_status"])
    linked, summaries = [], []
    for seq, row in by_seq.items():
        present = row_counts[seq] > 0
        total = totals[seq] if present else None
        if not present:
            warnings.append(f"No count rows supplied for {seq}; totals and fractions remain missing.")
        elif total == 0:
            warnings.append(f"Explicit count rows for {seq} sum to zero; read fractions are undefined.")
        if row["sorted_events"] == 0 and present and total > 0:
            warnings.append(f"{seq} has reads but its supplied sorted-event count is zero; investigate provenance.")
        source_sample = samples[row["sample_id"]]
        if source_sample["qc_flags"]:
            warnings.append(f"FCS sample {row['sample_id']} has upstream QC flags; linkage does not clear them.")
        summaries.append({**row, "count_status":"provided" if present else "missing",
                          "total_reads":total,"observed_variant_rows":row_counts[seq],
                          "variants_with_positive_reads":sum(1 for c in counts if c["sequencing_sample_id"]==seq and c["read_count"]>0),
                          "upstream_gate_status":source_sample["gate_status"],
                          "upstream_qc_flags":source_sample["qc_flags"]})
    for row in counts:
        seq = row["sequencing_sample_id"]; b = by_seq[seq]
        linked.append({**row,"bin_id":b["bin_id"],"sample_id":b["sample_id"],
                       "gate_definition_id":b["gate_definition_id"],"sorted_events":b["sorted_events"],
                       "total_reads_in_sequencing_sample":totals[seq],
                       "read_fraction_within_sequencing_sample":row["read_count"]/totals[seq] if totals[seq] else None,
                       "below_advisory_read_threshold":row["read_count"]<min_reads})
    low = sum(r["below_advisory_read_threshold"] for r in linked)
    if low:
        warnings.append(f"{low} supplied variant/bin rows have fewer than {min_reads} reads (advisory threshold only).")
    return {"schema_version":"yeast-sortseq-linked/v1","evidence_kind":experiment["evidence_kind"],
            "analysis_status":"descriptive_linkage_only",
            "upstream_comparison_status":experiment["comparison_status"],
            "upstream_warnings":experiment["warnings"],
            "parameters":{"advisory_min_reads":min_reads},
            "samples_referenced":sorted({b["sample_id"] for b in bins}),
            "observed_variant_ids":sorted(variants),"bins":summaries,"linked_counts":linked,
            "warnings":list(dict.fromkeys(warnings)),
            "not_implemented":["FASTQ decoding", "barcode sequence verification", "Tite-Seq affinity fitting",
                               "cell-fraction estimation", "enrichment against an input library", "biological validation"]}


def synthetic_inputs(experiment):
    samples = samples_by_id(experiment)
    if experiment["evidence_kind"] != "synthetic":
        raise ValidationError("demo refuses non-synthetic experiment inputs; provide your actual sort map and counts")
    sid = next((s for s, r in samples.items() if r.get("control_role") == "sample"), next(iter(samples)))
    bins, counts = [], []
    for i in range(4):
        seq = f"synthetic_seq_{i+1}"
        bins.append({"bin_id":f"synthetic_bin_{i+1}","sample_id":sid,
                     "sequencing_sample_id":seq,"sorted_events":1000+100*i,
                     "gate_definition_id":f"illustration_only_{i+1}"})
        for j, n in enumerate([800-180*i,150+100*i,50+80*i]):
            counts.append({"sequencing_sample_id":seq,"variant_id":f"synthetic_variant_{j+1}","read_count":n})
    return ({"schema_version":"yeast-sort-bins/v1","evidence_kind":"synthetic","bins":bins},
            {"schema_version":"yeast-variant-counts/v1","evidence_kind":"synthetic","counts":counts})
