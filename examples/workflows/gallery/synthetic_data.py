"""Deterministic, invented event and decoded-count fixtures for a public gallery.

No experimental input files are read. The artificial sort-count model is separate
from the event cloud: its association is a demonstration of explicit identifiers,
not a reconstruction of a sequencing or sorting experiment.
"""

from __future__ import annotations

import hashlib
import json
import math

from aureka_flow.workflows.core.core import summarize_events
from aureka_flow.workflows.workbench.analysis import analyze
from aureka_flow.workflows.sortseq.linkage import link_experiment


DETECTORS = ["FSC-A", "SSC-A", "FITC-A", "APC-A", "Time"]
CONDITIONS = ["Baseline", "Shift A", "Shift B"]
SOURCE_SERIALIZATION = (
    "UTF-8 json.dumps(events.tolist(), separators=(',', ':'), allow_nan=False) "
    "followed by one newline; hash describes an invented event array, not an FCS file"
)


def _parameters(seed, events_per_sample):
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError("seed must be an integer in [0, 2**64), not a boolean")
    if type(events_per_sample) is not int or not 100 <= events_per_sample <= 100_000:
        raise ValueError("events_per_sample must be an integer in [100, 100000], not a boolean")


def _source_hash(events):
    payload = json.dumps(events.tolist(), separators=(",", ":"), allow_nan=False) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_dataset(seed=20261001, events_per_sample=3000):
    """Return arrays and actual pipeline outputs, all explicitly synthetic.

    ``samples[].qc_mask`` is True for retained events (outside 80 <= Time < 100).
    ``selected_mask`` additionally requires FITC-A >= 400. Events are in original
    acquisition order. Simulated replicate labels are not physical replicates.

    Reproduction requires the same seed, parameters and compatible NumPy random
    implementation; the returned metadata records the observed NumPy version.
    No global random state is modified. No files are read or written.
    """
    _parameters(seed, events_per_sample)
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("The synthetic gallery requires the optional NumPy dependency") from exc

    rng = np.random.Generator(np.random.PCG64(seed))
    levels = {"Baseline": 70.0, "Shift A": 250.0, "Shift B": 900.0}
    condition_slug = {"Baseline": "baseline", "Shift A": "shift-a", "Shift B": "shift-b"}
    generation = {
        "scatter": {
            "FSC_A_lognormal_median": 50_000.0, "FSC_A_log_sigma": 0.25,
            "SSC_A_lognormal_median": 26_000.0, "SSC_A_log_sigma": 0.20,
            "log_scatter_correlation": 0.72,
        },
        "expression": {
            "main_lognormal_median": 1000.0, "main_log_sigma": 0.45,
            "low_expression_probability": 0.12, "low_lognormal_median": 110.0,
            "low_log_sigma": 0.34, "replicate_log_sigma": 0.045,
        },
        "binding": {
            "nominal_condition_levels": levels, "expression_exponent": 0.8,
            "multiplicative_log_sigma": 0.25, "additive_normal_sigma": 12.0,
            "replicate_log_sigma": 0.07,
            "formula": "condition_level * replicate_factor * (FITC_A/1000)**0.8 * exp(N(0,0.25)) + N(0,12)",
            "negative_values": "Preserved; additive noise can create finite negative fluorescence",
        },
        "time": {"start_seconds": 0.0, "end_seconds": 180.0, "spacing": "numpy.linspace with both endpoints included"},
        "injected_transient": {
            "channel": "APC-A", "start_inclusive_seconds": 80.0, "end_exclusive_seconds": 100.0,
            "formula": "Add 450 + 1.2 * nominal_condition_level to APC-A in the predetermined interval",
            "purpose": "A conspicuous invented artifact to illustrate masking, not an empirically estimated acquisition failure",
        },
        "external_qc_mask": {
            "rule": "Keep events outside 80 <= Time < 100 seconds",
            "discovery": "Predetermined from the simulation definition, not automatically detected",
            "PeacoQC_executed": False, "time_channel_repair": False,
        },
        "supplied_fluorescence_gate": {
            "channel": "FITC-A", "minimum_inclusive": 400.0, "maximum_exclusive": None,
            "binding_channel_gate": None, "biological_validation": False,
            "scope": "exploratory", "interpretation": "Demonstration expression cutoff, not a validated yeast/singlet/live gate",
        },
    }
    samples = []
    measurements = {"schema_version": "yeast-facs-measurements/v1", "evidence_kind": "synthetic", "samples": []}
    manifest = {
        "schema_version": "yeast-facs-samples/v1", "evidence_kind": "synthetic",
        "description": "SYNTHETIC ONLY: three artificial conditions and three simulated replicate labels per condition. No physical biological replicates or measured controls.",
        "samples": [],
    }
    per_sample_parameters = []
    for condition in CONDITIONS:
        for replicate_index in range(1, 4):
            sample_id = f"synthetic-{condition_slug[condition]}-r{replicate_index}"
            replicate = f"Simulated R{replicate_index}"
            expression_factor = float(math.exp(rng.normal(0.0, 0.045)))
            binding_factor = float(math.exp(rng.normal(0.0, 0.07)))
            z1 = rng.normal(size=events_per_sample)
            z2 = rng.normal(size=events_per_sample)
            fsc = np.exp(math.log(50_000.0) + 0.25 * z1)
            ssc = np.exp(math.log(26_000.0) + 0.20 * (0.72 * z1 + math.sqrt(1 - 0.72**2) * z2))
            expression = rng.lognormal(math.log(1000.0), 0.45, size=events_per_sample) * expression_factor
            low_expression = rng.random(events_per_sample) < 0.12
            expression[low_expression] = rng.lognormal(math.log(110.0), 0.34, size=int(low_expression.sum())) * expression_factor
            binding = (levels[condition] * binding_factor * (expression / 1000.0) ** 0.8
                       * np.exp(rng.normal(0.0, 0.25, events_per_sample))
                       + rng.normal(0.0, 12.0, events_per_sample))
            time = np.linspace(0.0, 180.0, events_per_sample)
            transient = (time >= 80.0) & (time < 100.0)
            binding[transient] += 450.0 + 1.2 * levels[condition]
            events = np.column_stack((fsc, ssc, expression, binding, time)).astype(np.float64, copy=False)
            qc_mask = ~transient
            selected_mask = qc_mask & (expression >= 400.0)
            source = {"basename": sample_id + "-events.json", "sha256": _source_hash(events)}
            config = {
                "schema_version": "yeast-facs-analysis-config/v1", "sample_id": sample_id,
                "evidence_kind": "synthetic", "channels": ["FITC-A", "APC-A"],
                "compensation": {"state": "uncompensated", "reason": "Synthetic detector values with no spillover model; not a recommendation for experimental compensation"},
                "rectangle_gates": [{
                    "gate_id": "synthetic-expression-at-least-400", "scope": "exploratory",
                    "reference_status": "Predetermined illustrative cutoff; no biological control-derived validation",
                    "bounds": {"FITC-A": {"min": 400.0, "max": None}},
                }],
            }
            external_mask = {
                "schema_version": "yeast-facs-qc-mask/v1", "source_sha256": source["sha256"],
                "event_count": events_per_sample,
                "kept_original_event_indices": np.flatnonzero(qc_mask).tolist(),
                "method": "Predetermined synthetic 80 <= Time < 100 second exclusion; not automatic detection or PeacoQC execution",
            }
            measured = summarize_events(
                events, DETECTORS, config, source=source, qc_mask=external_mask,
                metadata={"btim": "12:00:00", "etim": "12:03:00", "timestep": "1"},
                time_preprocessed=False, engine="numpy_synthetic_gallery_then_actual_summarize_events",
            )["samples"][0]
            measured["processing"]["synthetic_source_serialization"] = SOURCE_SERIALIZATION
            measured["processing"]["event_origin"] = "Entirely invented NumPy array, not an imported FCS acquisition"
            measurements["samples"].append(measured)
            manifest["samples"].append({
                "sample_id": sample_id, "condition": condition,
                "biological_replicate": "simulated-only-" + condition_slug[condition] + f"-r{replicate_index}",
                "batch_id": "synthetic-single-batch", "plate": "synthetic-plate",
                "well": f"{chr(65 + CONDITIONS.index(condition))}{replicate_index}", "control_role": "sample",
            })
            samples.append({"sample_id": sample_id, "condition": condition, "replicate": replicate,
                            "events": events, "qc_mask": qc_mask, "selected_mask": selected_mask})
            per_sample_parameters.append({
                "sample_id": sample_id, "expression_replicate_factor": expression_factor,
                "binding_replicate_factor": binding_factor, "generated_low_expression_events": int(low_expression.sum()),
                "injected_transient_events": int(transient.sum()), "qc_retained_events": int(qc_mask.sum()),
                "selected_events": int(selected_mask.sum()),
            })

    # These toy bin-count probabilities are independent of the simulated points.
    # The sample ID below is an explicit illustrative join, not a sort inference.
    sort_source = "synthetic-shift-b-r1"
    variant_ids = [f"synthetic-variant-{i:02d}" for i in range(1, 9)]
    preference_centers = np.linspace(-1.6, 1.6, 8)
    bin_centers = [-1.5, -0.5, 0.5, 1.5]
    abundance_weights = np.array([1.00, 0.90, 1.10, 1.05, 0.95, 1.15, 0.85, 1.00])
    width = 0.7
    read_depths = [24_000, 30_000, 22_000, 26_000]
    sort_counters = [8_000, 6_000, 4_000, 2_000]
    sort_description = (
        "SYNTHETIC: four categorical bins and eight invented variant IDs. Counts and sort counters "
        "are modeled independently of event clouds. No event-derived bin boundaries, sequences, "
        "FASTQ decoding, cell fractions, affinity or biological measurements."
    )
    sort_bins = {"schema_version": "yeast-sort-bins/v1", "evidence_kind": "synthetic", "description": sort_description, "bins": []}
    variant_counts = {"schema_version": "yeast-variant-counts/v1", "evidence_kind": "synthetic", "description": sort_description, "counts": []}
    probabilities = []
    for index, center in enumerate(bin_centers):
        weights = abundance_weights * np.exp(-0.5 * ((preference_centers - center) / width) ** 2)
        probability = weights / weights.sum()
        probabilities.append(probability.tolist())
        sampled_counts = rng.multinomial(read_depths[index], probability)
        seq_id = f"synthetic-seq-bin-{index + 1}"
        sort_bins["bins"].append({
            "bin_id": f"synthetic-bin-{index + 1}", "sample_id": sort_source,
            "sequencing_sample_id": seq_id, "sorted_events": sort_counters[index],
            "gate_definition_id": f"illustration-only-categorical-bin-{index + 1}",
        })
        for variant_id, count in zip(variant_ids, sampled_counts):
            variant_counts["counts"].append({"sequencing_sample_id": seq_id, "variant_id": variant_id, "read_count": int(count)})

    experiment = analyze(measurements, manifest)
    linked = link_experiment(experiment, sort_bins, variant_counts)
    metadata = {
        "schema_version": "yeast-facs-gallery-synthetic/v1", "evidence_kind": "synthetic",
        "title": "Entirely synthetic yeast-FACS workflow illustration",
        "seed": seed, "numpy_version": np.__version__, "random_bit_generator": "PCG64",
        "events_per_sample": events_per_sample, "sample_count": len(samples), "total_event_count": len(samples) * events_per_sample,
        "conditions": list(CONDITIONS), "simulated_replicates_per_condition": 3,
        "replicate_labels": ["Simulated R1", "Simulated R2", "Simulated R3"],
        "replicate_semantics": "Independent random draws and modest seeded offsets for illustration; labels in the biological_replicate field are explicitly simulated, not physical biological replicates",
        "real_biological_replicates": 0, "real_data_sources": [], "experimental_measurements": False,
        "batch_id": "synthetic-single-batch", "detectors": list(DETECTORS),
        "detector_roles": {"FSC-A": "synthetic size-like scatter", "SSC-A": "synthetic complexity-like scatter",
                           "FITC-A": "synthetic expression-like fluorescence", "APC-A": "synthetic binding-like fluorescence", "Time": "synthetic acquisition time"},
        "units": {"FSC-A": "synthetic arbitrary units", "SSC-A": "synthetic arbitrary units", "FITC-A": "synthetic arbitrary units", "APC-A": "synthetic arbitrary units", "Time": "seconds"},
        "generation_parameters": generation, "per_sample_parameters": per_sample_parameters,
        "source_hash_serialization": SOURCE_SERIALIZATION,
        "qc_mask_semantics": "True means keep; the fixed excluded interval is known from construction, not automatically discovered",
        "selected_mask_semantics": "qc_mask AND FITC-A >= 400; no APC-A selection",
        "sort_count_model": {
            "description": sort_description, "independent_of_event_cloud": True, "source_sample_id": sort_source,
            "variant_ids": variant_ids, "arbitrary_variant_preference_centers": preference_centers.tolist(),
            "arbitrary_bin_centers": bin_centers, "preference_width": width,
            "relative_abundance_weights": abundance_weights.tolist(), "read_depths": read_depths,
            "declared_sorted_event_counters": sort_counters, "bin_variant_probabilities": probabilities,
            "formula": "Within each invented bin, probabilities are proportional to abundance_weight * exp(-0.5*((variant_preference-bin_center)/0.7)**2); draw integer counts with NumPy multinomial",
            "reported_endpoint": "Within-sequencing-sample read fractions, not cell fractions or affinity",
        },
        "executed_components": ["summarize_events", "workbench.analyze", "bridge.link_experiment"],
        "not_executed": ["native FCS decoding", "FlowKit", "PeacoQC", "automatic acquisition-error detection", "FASTQ decoding", "affinity fitting", "biological validation"],
        "scientific_limits": [
            "Condition shifts and transient artifacts are programmed assumptions, not discoveries.",
            "Simulated replicate spread is not biological reproducibility or a statistical significance claim.",
            "The expression rectangle is illustrative; selected events are not validated live singlets.",
            "The separate count model does not reconstruct sorting from these event points.",
            "Fluorescence and read fractions are not affinity.",
        ],
    }
    return {"metadata": metadata, "samples": samples, "detectors": list(DETECTORS),
            "measurements": measurements, "manifest": manifest, "experiment": experiment,
            "sort_bins": sort_bins, "variant_counts": variant_counts, "linked": linked}
