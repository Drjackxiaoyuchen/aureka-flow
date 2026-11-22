"""The batch adapter must honor the browser's embedded-matrix safeguards.

All events and metadata here are generated fixtures, not BD export validation.
"""
import hashlib
import io
import json

import flowio
import numpy as np
import pytest

from aureka_flow.engine import AnalysisEngine
from aureka_flow.workflows.core.cli import main as core_main
from aureka_flow.workflows.core.core import analyze_fcs
from aureka_flow.workflows.pipeline import run_batch


SPILL = "2,FITC-A,APC-A,1,0.1,0.2,1"
EVENTS = np.array([[30., 6.], [10., 2.], [20., 4.]])


def config(state="embedded"):
    return {"schema_version": "yeast-facs-analysis-config/v1", "sample_id": "synthetic-a",
            "evidence_kind": "synthetic", "channels": ["FITC-A", "APC-A"],
            "compensation": {"state": state, "reason": "Synthetic regression fixture"}}


def make_fcs(tmp_path, metadata):
    handle = io.BytesIO()
    flowio.create_fcs(handle, EVENTS.ravel().tolist(), ["FITC-A", "APC-A"], metadata_dict=metadata)
    path = tmp_path / "synthetic.fcs"
    path.write_bytes(handle.getvalue())
    return path


@pytest.mark.parametrize("metadata, error", [
    ({"spill": SPILL, "spillover": "2,FITC-A,APC-A,1,0,0,1"}, "Conflicting"),
    ({"spillover": "2,FITC-A,APC-A,1,nan,0,1"}, "non-finite"),
    ({"spillover": "2,FITC-A,APC-A,1,inf,0,1"}, "non-finite"),
    ({"spillover": "2,FITC-A,APC-A,1,1,1,1"}, "config.compensation"),
    ({"spillover": "broken"}, "config.compensation"),
])
def test_browser_and_batch_refuse_the_same_unusable_matrix(tmp_path, metadata, error):
    path = make_fcs(tmp_path, metadata)
    original = path.read_bytes()
    browser = AnalysisEngine().load(original, path.name)
    assert not browser["compensation_available"]
    with pytest.raises(ValueError, match=error):
        analyze_fcs(path, config())
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config()), encoding="utf-8")
    output = tmp_path / "must-not-exist.json"
    assert core_main(["analyze", str(path), "--config", str(cfg), "--output", str(output)]) == 2
    assert not output.exists()
    assert path.read_bytes() == original


@pytest.mark.parametrize("metadata", [
    {"spill": SPILL}, {"spillover": SPILL},
    {"spill": SPILL, "spillover": "2,FITC-A,APC-A,1.0,0.10,0.20,1.0"},
])
def test_valid_matrix_corrects_known_values_and_preserves_keyword_hashes(tmp_path, metadata):
    path = make_fcs(tmp_path, metadata)
    sample = analyze_fcs(path, config())["samples"][0]
    assert sample["selected_count"] == 3
    assert sample["processing"]["selected_event_ranges"] == [[0, 3]]
    assert sample["source"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    # Independently solve the known two-detector mixing equations at the median event.
    assert sample["channels"]["FITC-A"]["median"] == pytest.approx((20 - .2 * 4) / .98)
    assert sample["channels"]["APC-A"]["median"] == pytest.approx((4 - .1 * 20) / .98)
    assert sample["processing"]["embedded_matrix_keyword_sha256"] == {
        key: hashlib.sha256(value.encode()).hexdigest() for key, value in metadata.items()}
    chosen = metadata.get("spillover") or metadata["spill"]
    assert sample["processing"]["embedded_spillover_sha256"] == hashlib.sha256(chosen.encode()).hexdigest()
    assert sample["processing"]["source_compensation_state"] == "unverified"


@pytest.mark.parametrize("state", ["uncompensated", "already_compensated"])
def test_source_mode_does_not_apply_or_require_a_usable_matrix(tmp_path, state):
    path = make_fcs(tmp_path, {"spill": SPILL, "spillover": "broken"})
    sample = analyze_fcs(path, config(state))["samples"][0]
    assert sample["channels"]["FITC-A"]["median"] == 20
    assert sample["channels"]["APC-A"]["median"] == 4
    assert sample["processing"]["selected_event_ranges"] == [[0, 3]]
    assert sample["processing"]["compensation"]["state"] == state
    assert sample["processing"]["source_compensation_state"] == "unverified"
    assert "embedded_matrix_keyword_sha256" not in sample["processing"]


def test_conflicting_matrix_stops_batch_before_creating_any_output(tmp_path):
    path = make_fcs(tmp_path, {"spill": SPILL, "spillover": "2,FITC-A,APC-A,1,0,0,1"})
    (tmp_path / "config.json").write_text(json.dumps(config()), encoding="utf-8")
    manifest = {"schema_version": "yeast-facs-samples/v1", "samples": [{
        "sample_id": "synthetic-a", "condition": "synthetic", "biological_replicate": None,
        "batch_id": "synthetic-batch", "plate": None, "well": None, "control_role": "sample"}]}
    (tmp_path / "samples.json").write_text(json.dumps(manifest), encoding="utf-8")
    run = {"schema_version": "yeast-facs-run/v1", "files": [{"fcs": path.name, "config": "config.json"}],
           "sample_manifest": "samples.json"}
    run_file = tmp_path / "run.json"
    run_file.write_text(json.dumps(run), encoding="utf-8")
    with pytest.raises(ValueError, match="Conflicting"):
        run_batch(run_file, tmp_path / "output")
    assert not (tmp_path / "output").exists()
