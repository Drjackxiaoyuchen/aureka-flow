"""Connect exact browser gate membership to the experiment-report contract."""
from __future__ import annotations

import numpy as np

from .. import __version__
from ..engine import ComparisonSpec, StrictModel
from .core.core import _ranges, time_qc
from .workbench.analysis import analyze


class ExperimentSpec(StrictModel):
    analysis: ComparisonSpec
    manifest: dict | None = None


def acquisition_qc(rec):
    """Diagnostics describe original acquisition order and never remove events."""
    events = rec.sample.get_events(source="raw")
    channels = rec.sample.pnn_labels
    index = next((i for i, name in enumerate(channels) if name.lower() == "time"), None)
    flags, detail = time_qc(None if index is None else events[:, index], rec.sample.metadata,
                            preprocessed=True)
    nonfinite = {name: int((~np.isfinite(events[:, i])).sum()) for i, name in enumerate(channels)}
    if any(nonfinite.values()):
        flags.append("nonfinite_input_measurements")
    return {"source_sha256": rec.digest, "event_count": rec.sample.event_count,
            "flags": flags, "time": detail, "nonfinite_counts": nonfinite,
            "automatic_event_exclusion": False}


def sample_records(engine, spec):
    if len(spec.sample_ids) != len(set(spec.sample_ids)):
        raise ValueError("Choose each sample once; repeated acquisitions are not extra replicates.")
    return [engine.record(uid) for uid in spec.sample_ids]


def manifest_template(engine, spec):
    records = sample_records(engine, spec)
    return {"schema_version": "yeast-facs-samples/v1",
            "description": "Replace Unspecified with your condition. Fill known biological replicate and batch identities; null means unknown. sample_id is the source FCS SHA-256.",
            "samples": [{"sample_id": rec.digest, "condition": "Unspecified",
                         "biological_replicate": None, "batch_id": None,
                         "plate": None, "well": None, "control_role": "sample"} for rec in records]}


def experiment_inputs(engine, spec, manifest=None):
    records = sample_records(engine, spec)
    kinds = {"synthetic" if rec.origin.startswith("Synthetic demo ·") else "user_data" for rec in records}
    if len(kinds) != 1:
        raise ValueError("Choose synthetic demo samples or uploaded FCS samples in one report.")
    samples = []
    by_name = {gate.name: gate for gate in engine.gates}
    chain, name = [], spec.population
    while name != "root":
        if name not in by_name:
            raise ValueError(f"Population '{name}' does not exist.")
        gate = by_name[name]
        chain.insert(0, gate.model_dump(mode="json"))
        name = gate.parent
    for rec in records:
        engine.validate_sample(rec)
        mask = engine.mask(rec, spec.population)
        indices = np.flatnonzero(mask).tolist()
        qc = acquisition_qc(rec)
        events = engine.events(rec, spec.compensation)
        channels = {}
        for channel in dict.fromkeys(axis.channel for axis in (spec.x, spec.y) if axis is not None):
            if channel not in rec.sample.pnn_labels:
                raise ValueError(f"Channel '{channel}' is missing from {rec.filename}.")
            values = events[mask, rec.sample.get_channel_index(channel)]
            finite = values[np.isfinite(values)]
            channels[channel] = {"median": float(np.median(finite)) if len(finite) else None,
                                 "finite_count": len(finite), "negative_count": int((finite < 0).sum())}
        flags = list(qc["flags"])
        if spec.compensation == "raw":
            flags.append("fluorescence_uncompensated")
        if not indices:
            flags.append("no_selected_events")
        if engine.workspace and engine.workspace["mode"] == "reconstructed":
            flags.append("instrument_gates_reconstructed_not_vendor_count_validated")
        samples.append({"sample_id": rec.digest,
                        "source": {"basename": rec.filename, "sha256": rec.digest},
                        "event_count": rec.sample.event_count, "selected_count": len(indices),
                        "gate_status": "ungated" if spec.population == "root" else "user_supplied_unvalidated",
                        "channels": channels, "qc_flags": flags,
                        "processing": {"engine": "Aureka Flow/" + __version__,
                                       "selection": "all_events" if spec.population == "root" else "saved_browser_population",
                                       "population": spec.population, "gates": chain,
                                       "selected_event_ranges": _ranges(indices),
                                       "range_semantics": "start_inclusive_end_exclusive",
                                       "event_identity": "zero_based_original_FCS_DATA_order",
                                       "compensation": spec.compensation,
                                       "transformation": "none; FlowKit preprocessed detector units",
                                       "summary_denominator": "per-channel finite_count among selected_count",
                                       "time_qc": qc["time"], "input_nonfinite_counts": qc["nonfinite_counts"],
                                       "automatic_qc_exclusion": False}})
        if engine.workspace:
            samples[-1]["processing"]["imported_workspace"] = {
                "xml_sha256": engine.workspace["source"]["sha256"],
                "worksheet": engine.workspace["worksheet"], "mode": engine.workspace["mode"],
                "sample_index": engine.workspace["bindings"].get(rec.digest),
                "note": engine.workspace["reconstruction_note"]}
        if spec.compensation == "xml":
            samples[-1]["processing"]["xml_spillover_matrix"] = rec.xml_compensation.matrix.tolist()
            samples[-1]["processing"]["xml_spillover_detectors"] = list(rec.xml_compensation.detectors)
            samples[-1]["processing"]["source_compensation_state"] = "unverified"
    measurements = {"schema_version": "yeast-facs-measurements/v1", "evidence_kind": kinds.pop(), "samples": samples}
    manifest = manifest_template(engine, spec) if manifest is None else manifest
    return measurements, manifest, analyze(measurements, manifest)
