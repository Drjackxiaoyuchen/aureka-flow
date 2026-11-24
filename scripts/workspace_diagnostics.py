"""Local full-event replay diagnostics; no independent FlowJo memberships are inferred."""
from __future__ import annotations

import hashlib
import json

import flowkit as fk
import numpy as np


def mask_digest(mask):
    """SHA-256 of one uint8 (0/1) per source event, in original event order."""
    return hashlib.sha256(np.asarray(mask, dtype=np.uint8).tobytes()).hexdigest()


def interval_diagnostics(values, lower, upper, parent):
    """Literal interval arithmetic, with no rounding, clipping or boundary tolerance."""
    selected = np.ones(len(values), dtype=bool)
    if lower is not None:
        selected &= values >= lower
    if upper is not None:
        selected &= values < upper
    finite = values[parent & np.isfinite(values)]
    return selected, {
        "minimum_inclusive": lower, "maximum_exclusive": upper,
        "finite_parent_minimum": float(finite.min()) if len(finite) else None,
        "finite_parent_maximum": float(finite.max()) if len(finite) else None,
        "nonfinite_parent_events": int(np.count_nonzero(parent & ~np.isfinite(values))),
        "parent_below_minimum": int(np.count_nonzero(parent & (values < lower))) if lower is not None else None,
        "parent_equal_minimum": int(np.count_nonzero(parent & (values == lower))) if lower is not None else None,
        "parent_equal_maximum": int(np.count_nonzero(parent & (values == upper))) if upper is not None else None,
        "parent_at_or_above_maximum": int(np.count_nonzero(parent & (values >= upper))) if upper is not None else None,
        "parent_passing_dimension": int(np.count_nonzero(parent & selected)),
    }


def rectangle_diagnostics(sample, strategy, gate, parent, replayed):
    """Check imported rectangle inequalities, reusing the imported transform functions.

    This deliberately supports exact PnN detector labels and one named matrix.
    Other mappings/derived dimensions are reported as undiagnosed, never guessed.
    """
    if any(type(dim) is not fk.Dimension for dim in gate.dimensions):
        return {"status": "not diagnosed", "reason": "Derived dimensions are outside diagnostic scope."}
    if any(dim.id not in sample.pnn_labels for dim in gate.dimensions):
        return {"status": "not diagnosed", "reason": "Requires exact source detector labels; no alias mapping is inferred."}
    refs = {dim.compensation_ref for dim in gate.dimensions
            if dim.compensation_ref not in (None, "uncompensated")}
    if len(refs) > 1 or "FCS" in refs:
        return {"status": "not diagnosed", "reason": "Requires source values or one named workspace matrix."}
    events = sample.get_events(source="raw").copy()
    matrix_info = None
    if refs:
        ref = next(iter(refs))
        matrix = strategy.get_comp_matrix(ref)
        if matrix is None:
            return {"status": "not diagnosed", "reason": "Named workspace matrix is unavailable."}
        indices = [sample.get_channel_index(label) for label in matrix.detectors]
        # Independently solve the mixing equations, rather than invoking Matrix.apply.
        events[:, indices] = np.linalg.solve(matrix.matrix.T, events[:, indices].T).T
        identity = {"detectors": matrix.detectors, "coefficients": matrix.matrix.tolist()}
        matrix_info = {"reference": ref, "detectors": matrix.detectors,
                       "sha256": hashlib.sha256(json.dumps(identity, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()}
    selected = np.ones(sample.event_count, dtype=bool)
    dimensions = []
    for dim in gate.dimensions:
        values = events[:, sample.get_channel_index(dim.id)].copy()
        transform_info = None
        if dim.transformation_ref is not None:
            transform = strategy.get_transform(dim.transformation_ref)
            values = transform.apply(values)
            transform_info = {"reference": dim.transformation_ref, "type": type(transform).__name__,
                              "parameters": {key: value for key, value in vars(transform).items()
                                             if key.startswith("param_")}}
        dimension_mask, occupancy = interval_diagnostics(values, dim.min, dim.max, parent)
        selected &= dimension_mask
        dimensions.append({"detector": dim.id, "declared_compensation_reference": dim.compensation_ref,
                           "transform": transform_info, **occupancy})
    if gate.use_complement:
        selected = ~selected
    selected &= parent
    excluded = np.flatnonzero(parent & ~selected)
    return {"status": "diagnosed", "dimensions": dimensions, "effective_matrix": matrix_info,
            "use_complement": gate.use_complement,
            "literal_rectangle_count": int(np.count_nonzero(selected)),
            "excluded_parent_events": int(len(excluded)),
            "excluded_source_event_index_preview": excluded[:20].tolist(),
            "event_index_preview_limit": 20,
            "membership_difference_events": int(np.count_nonzero(selected ^ replayed)),
            "literal_membership_sha256": mask_digest(selected)}


def diagnose_sample(workspace, sample_id):
    sample = workspace.get_sample(sample_id)
    strategy = workspace.get_gating_strategy(sample_id)
    rows = []
    for name, path in workspace.get_gate_ids(sample_id):
        gate = workspace.get_gate(sample_id, name, path)
        parent = (np.ones(sample.event_count, dtype=bool) if path == ("root",) else
                  workspace.get_gate_membership(sample_id, path[-1], path[:-1]))
        replayed = workspace.get_gate_membership(sample_id, name, path)
        row = {"gate_path": list(path[1:] + (name,)), "gate_type": type(gate).__name__,
               "parent_events": int(np.count_nonzero(parent)), "replayed_count": int(np.count_nonzero(replayed)),
               "replayed_membership_sha256": mask_digest(replayed)}
        if type(gate) is fk.gates.RectangleGate:
            row["rectangle"] = rectangle_diagnostics(sample, strategy, gate, parent, replayed)
        else:
            row["rectangle"] = {"status": "not diagnosed", "reason": "Gate is not a rectangle."}
        rows.append(row)
    return {"sample": sample_id, "event_count": sample.event_count, "gates": rows}
