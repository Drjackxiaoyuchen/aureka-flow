"""Known synthetic events check diagnostic arithmetic, ancestry and honest scope."""
import subprocess
import sys
from pathlib import Path

import flowkit as fk
import numpy as np
import pytest

from scripts.workspace_diagnostics import diagnose_sample, interval_diagnostics, mask_digest, rectangle_diagnostics
from scripts import validate_workspace


class Workspace:
    """Use real FlowKit analysis behind the small public Workspace read interface."""
    def __init__(self):
        truth = np.array([[0, 0], [1, 0], [2, 0], [3, 2], [4, 0], [5, 2], [9, 0]], dtype=float)
        matrix = np.array([[1., .5], [0., 1.]])
        self.sample = fk.Sample(truth @ matrix, sample_id="synthetic", channel_labels=["A", "B"])
        self.strategy = fk.GatingStrategy()
        self.strategy.add_comp_matrix("mix", fk.Matrix(matrix, ["A", "B"]))
        self.strategy.add_transform("half", fk.transforms.LinearTransform(2., 0.))
        self.strategy.add_gate(fk.gates.RectangleGate("Parent", [fk.Dimension("A", range_min=1., range_max=5.)]), ("root",))
        for name, complement in [("Child", False), ("Complement", True)]:
            self.strategy.add_gate(fk.gates.RectangleGate(name, [fk.Dimension("B", compensation_ref="mix",
                transformation_ref="half", range_min=0., range_max=1.)], use_complement=complement), ("root", "Parent"))
        self.results = self.strategy.gate_sample(self.sample)

    def get_sample(self, _): return self.sample
    def get_gating_strategy(self, _): return self.strategy
    def get_gate_ids(self, _): return self.strategy.get_gate_ids()
    def get_gate(self, _, name, path): return self.strategy.get_gate(name, path)
    def get_gate_membership(self, _, name, path): return self.results.get_gate_membership(name, path)
    def get_sample_ids(self): return ["synthetic"]
    def get_gating_results(self, _): return self.results
    def analyze_samples(self, use_mp=False): pass


def test_named_matrix_transform_complement_and_parent_denominator():
    workspace = Workspace()
    original = workspace.sample.get_events(source="raw").copy()
    report = diagnose_sample(workspace, "synthetic")
    parent, child, complement = report["gates"]
    assert parent["parent_events"] == 7 and parent["replayed_count"] == 4
    assert child["gate_path"] == ["Parent", "Child"]
    assert child["parent_events"] == 4 and child["replayed_count"] == 3
    assert complement["replayed_count"] == 1
    assert child["rectangle"]["excluded_source_event_index_preview"] == [3]
    assert parent["rectangle"]["excluded_source_event_index_preview"] == [0, 5, 6]
    for row in report["gates"]:
        assert row["rectangle"]["membership_difference_events"] == 0
        assert row["replayed_membership_sha256"] == row["rectangle"]["literal_membership_sha256"]
    dim = child["rectangle"]["dimensions"][0]
    assert dim["parent_equal_minimum"] == 3 and dim["parent_equal_maximum"] == 1
    assert dim["transform"]["parameters"] == {"param_t": 2., "param_a": 0.}
    assert child["rectangle"]["effective_matrix"]["reference"] == "mix"
    np.testing.assert_array_equal(original, workspace.sample.get_events(source="raw"))


def test_equal_counts_with_different_event_ids_are_detected():
    workspace = Workspace()
    gate = workspace.strategy.get_gate("Parent")
    actual = workspace.results.get_gate_membership("Parent")
    wrong = actual.copy()
    wrong[0], wrong[1] = True, False
    assert wrong.sum() == actual.sum()
    result = rectangle_diagnostics(workspace.sample, workspace.strategy, gate, np.ones(7, dtype=bool), wrong)
    assert result["membership_difference_events"] == 2
    assert mask_digest(actual) != mask_digest(wrong)
    assert mask_digest(actual) == mask_digest(actual.astype(np.uint8))


def test_comparison_writes_hash_bound_optional_diagnostics(tmp_path, monkeypatch):
    import json
    workspace = Workspace()
    fcs_dir = tmp_path / "files"
    fcs_dir.mkdir()
    (fcs_dir / "synthetic.fcs").write_bytes(b"hash binding test; not an FCS fixture")
    # Use a matching source basename as Workspace does when importing this WSP.
    workspace.get_sample_ids = lambda: ["synthetic.fcs"]
    wsp = tmp_path / "reference.wsp"
    wsp.write_text('<Workspace flowJoVersion="test"><SampleList><Sample><SampleNode name="synthetic.fcs" count="7">'
        '<Subpopulations><Population name="Parent" count="4"><Subpopulations>'
        '<Population name="Child" count="3"/><Population name="Complement" count="1"/>'
        '</Subpopulations></Population></Subpopulations></SampleNode></Sample></SampleList></Workspace>', encoding="utf-8")
    monkeypatch.setattr(validate_workspace.fk, "Workspace", lambda *args, **kwargs: workspace)
    output = tmp_path / "out"
    rows, summary = validate_workspace.compare(wsp, fcs_dir, output, include_diagnostics=True)
    path = output / "gate-diagnostics.json"
    assert summary["exact_count_matches"] == 3 and len(rows) == 3
    assert summary["gate_diagnostics"]["sha256"] == validate_workspace.digest(path)
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["workspace_sha256"] == validate_workspace.digest(wsp)
    assert report["sources"][0]["sha256"] == validate_workspace.digest(fcs_dir / "synthetic.fcs")
    assert summary["gate_diagnostics"]["rectangle_gates_diagnosed"] == 3
    _, plain = validate_workspace.compare(wsp, fcs_dir, tmp_path / "plain")
    assert "gate_diagnostics" not in plain and not (tmp_path / "plain/gate-diagnostics.json").exists()


@pytest.mark.parametrize("lower,upper,expected", [(1., 2., [False, True, False]),
    (None, 1., [True, False, False]), (1., None, [False, True, True]), (None, None, [True, True, True])])
def test_open_ends_and_exact_boundary_convention(lower, upper, expected):
    mask, report = interval_diagnostics(np.array([0., 1., 2.]), lower, upper, np.ones(3, dtype=bool))
    assert mask.tolist() == expected
    assert report["parent_passing_dimension"] == sum(expected)


def test_empty_parent_nonfinite_values_and_no_boundary_tolerance():
    values = np.array([np.nan, np.inf, -np.inf, np.nextafter(1., 0.), 1., np.nextafter(1., 2.)])
    mask, report = interval_diagnostics(values, 1., 2., np.ones(6, dtype=bool))
    assert mask.tolist() == [False, False, False, False, True, True]
    assert report["nonfinite_parent_events"] == 3 and report["parent_equal_minimum"] == 1
    _, empty = interval_diagnostics(values, 1., None, np.zeros(6, dtype=bool))
    assert empty["finite_parent_minimum"] is None and empty["parent_passing_dimension"] == 0


def test_event_index_preview_is_bounded_without_sampling_membership():
    workspace = Workspace()
    workspace.sample = fk.Sample(np.zeros((100, 2)), sample_id="many", channel_labels=["A", "B"])
    gate = workspace.strategy.get_gate("Parent")
    result = rectangle_diagnostics(workspace.sample, workspace.strategy, gate, np.ones(100, dtype=bool), np.zeros(100, dtype=bool))
    assert result["excluded_parent_events"] == 100 and result["membership_difference_events"] == 0
    assert result["excluded_source_event_index_preview"] == list(range(20))


@pytest.mark.parametrize("dimension", [fk.Dimension("stain-alias"), fk.Dimension("A", compensation_ref="FCS"),
    fk.RatioDimension("ratio", "uncompensated")])
def test_unhandled_mapping_or_derived_dimension_is_explicit(dimension):
    workspace = Workspace()
    gate = fk.gates.RectangleGate("unsupported", [dimension])
    result = rectangle_diagnostics(workspace.sample, workspace.strategy, gate, np.ones(7, dtype=bool), np.zeros(7, dtype=bool))
    assert result["status"] == "not diagnosed" and "membership_difference_events" not in result


@pytest.mark.parametrize("source_ref", [None, "uncompensated"])
def test_mixed_source_and_matrix_fluorescence_is_not_silently_qualified(source_ref):
    # FlowKit 1.2.3 applies one matrix to the entire gate event array. A second
    # detector explicitly marked source values therefore has ambiguous semantics.
    truth = np.array([[1., 0.], [2., 2.], [3., 4.], [4., 1.]])
    mixing = np.array([[1., .5], [.25, 1.]])
    sample = fk.Sample(truth @ mixing, sample_id="mixed", channel_labels=["A", "B"])
    strategy = fk.GatingStrategy()
    strategy.add_comp_matrix("mix", fk.Matrix(mixing, ["A", "B"]))
    gate = fk.gates.RectangleGate("Mixed", [fk.Dimension("A", compensation_ref="mix", range_min=1., range_max=5.),
        fk.Dimension("B", compensation_ref=source_ref, range_min=0., range_max=3.)])
    strategy.add_gate(gate, ("root",))
    replayed = strategy.gate_sample(sample).get_gate_membership("Mixed")
    source = sample.get_events(source="raw").copy()
    declared = (truth[:, 0] >= 1.) & (truth[:, 0] < 5.) & (source[:, 1] >= 0.) & (source[:, 1] < 3.)
    assert np.flatnonzero(declared).tolist() == [0]
    assert np.flatnonzero(replayed).tolist() == [0, 1, 3]
    result = rectangle_diagnostics(sample, strategy, gate, np.ones(4, dtype=bool), replayed)
    assert result["status"] == "not diagnosed"
    assert "mixed" in result["reason"].lower()
    assert "membership_difference_events" not in result
    np.testing.assert_array_equal(sample.get_events(source="raw"), source)


def test_source_scatter_outside_the_matrix_remains_diagnosable():
    truth = np.array([[100., 1., 0.], [200., 2., 2.], [300., 3., 4.], [400., 4., 1.]])
    mixing = np.array([[1., .5], [.25, 1.]])
    recorded = truth.copy()
    recorded[:, 1:] = truth[:, 1:] @ mixing
    sample = fk.Sample(recorded, sample_id="scatter", channel_labels=["FSC-A", "A", "B"])
    strategy = fk.GatingStrategy()
    strategy.add_comp_matrix("mix", fk.Matrix(mixing, ["A", "B"]))
    gate = fk.gates.RectangleGate("Mixed scatter", [fk.Dimension("A", compensation_ref="mix", range_min=1., range_max=4.),
        fk.Dimension("FSC-A", compensation_ref="uncompensated", range_min=150., range_max=350.)])
    strategy.add_gate(gate, ("root",))
    replayed = strategy.gate_sample(sample).get_gate_membership("Mixed scatter")
    expected = (truth[:, 1] >= 1.) & (truth[:, 1] < 4.) & (truth[:, 0] >= 150.) & (truth[:, 0] < 350.)
    np.testing.assert_array_equal(replayed, expected)
    result = rectangle_diagnostics(sample, strategy, gate, np.ones(4, dtype=bool), replayed)
    assert result["status"] == "diagnosed" and result["membership_difference_events"] == 0
    assert result["literal_rectangle_count"] == 2


def test_direct_workspace_cli_can_load_diagnostic_module():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts/validate_workspace.py"), "--help"],
                            cwd=root.parent, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and "--diagnostics" in result.stdout
