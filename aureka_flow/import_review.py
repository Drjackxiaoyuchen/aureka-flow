"""Review source metadata without inferring an instrument's export processing."""
import flowkit as fk
import numpy as np


def prepare_embedded_compensation(sample):
    """Accept one unambiguous finite matrix; keep source values on failure."""
    values = [sample.metadata[key] for key in ("spillover", "spill") if sample.metadata.get(key)]
    if not values:
        return None
    try:
        detectors = [sample.pnn_labels[i] for i in sample.fluoro_indices]
        stains = [sample.pns_labels[i] for i in sample.fluoro_indices]
        matrices = [fk.Matrix(value, detectors, stains) for value in values]
        if any(not np.isfinite(matrix.matrix).all() for matrix in matrices):
            raise ValueError("Embedded spillover contains non-finite values. Re-export a finite matrix.")
        if any(matrix != matrices[0] for matrix in matrices[1:]):
            raise ValueError("Conflicting SPILL and SPILLOVER matrices. Re-export one verified matrix.")
        sample.apply_compensation(matrices[0])
    except Exception as exc:
        return str(exc)
    return None


def import_review(sample, compensation_error):
    metadata = sample.get_metadata()
    keywords = [key for key in ("spillover", "spill") if metadata.get(key)]
    return {
        "source_reported": {key: metadata.get(key) for key in ("cyt", "creator", "date", "btim", "etim", "timestep")},
        "embedded_matrix_keywords": keywords,
        "embedded_matrix_status": "unusable" if compensation_error else "usable" if sample.compensation is not None else "missing",
        "source_compensation_state": "unverified",
        "review_note": "An embedded matrix does not establish whether the source values were already compensated or unmixed. "
                       "Confirm the export settings before applying additional compensation. "
                       "Source values include standard FCS gain/log/time preprocessing.",
    }
