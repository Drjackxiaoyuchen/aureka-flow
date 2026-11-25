"""Offline acceptance-contract tests; the public experimental run is opt-in."""
import hashlib

import numpy as np
import pytest

from scripts import qualify_public_reference as public


def test_byte_reference_preserves_order_and_only_scales_time():
    events = np.array([[3., 20.], [1., 10.], [2., 30.]], dtype="<f4")
    layout = {"event_count": 3, "channel_count": 2, "dtype": "<f4", "data_offset": 4,
              "time_channel_index": 1, "time_step": .01}
    decoded = public.binary_reference(b"test" + events.tobytes(), layout)
    np.testing.assert_array_equal(decoded, [[3, .2], [1, .1], [2, .3]])
    with pytest.raises(ValueError, match="complete DATA"):
        public.binary_reference(b"test" + events.tobytes()[:-1], layout)


def test_reference_mixing_equations_use_detector_identity_and_keep_other_channels():
    raw = np.array([[99., 20., 4.], [5., 10., 2.]])
    values, indices = public.compensation_reference(raw, ["FSC-A", "B", "A"], "2,A,B,1,.1,.2,1")
    assert indices == [2, 1]
    # A = (observed A - .2 * observed B) / .98.
    np.testing.assert_allclose(values[:, 2], [0., 0.], atol=1e-12)
    np.testing.assert_allclose(values[:, 1], [20., 10.])
    np.testing.assert_array_equal(values[:, 0], raw[:, 0])
    np.testing.assert_array_equal(raw, [[99., 20., 4.], [5., 10., 2.]])


@pytest.mark.parametrize("spill", ["2,A,A,1,0,0,1", "2,A,B,1,0,1", "2,A,B,1,nan,0,1"])
def test_invalid_reference_matrix_never_passes(spill):
    with pytest.raises(ValueError):
        public.compensation_reference(np.ones((2, 2)), ["A", "B"], spill)


def summary():
    return {"gate_sample_rows": 14, "comparable_rows": 14, "exact_count_matches": 14,
            "sources": [{"sample": "selected", "root_counts_match": True}]}


def test_equal_counts_need_complete_nonempty_reference_scope():
    assert public.count_agreement(summary(), 14, "selected")["exact_count_agreement"]
    assert not public.count_agreement(summary(), 0, "selected")["exact_count_agreement"]
    assert not public.count_agreement(summary(), 14, "wrong sample")["exact_count_agreement"]
    assert not public.count_agreement(summary() | {"comparable_rows": 13}, 14, "selected")["complete_for_selected_scope"]
    assert not public.count_agreement(summary() | {"sources": []}, 14, "selected")["complete_for_selected_scope"]
    assert not public.count_agreement(summary() | {"sources": [{"sample": "selected", "root_counts_match": False}]}, 14, "selected")["exact_count_agreement"]


def test_small_count_disagreement_is_reported_without_tolerance_tuning():
    status = public.count_agreement(summary() | {"exact_count_matches": 13}, 14, "selected")
    assert status == {"complete_for_selected_scope": True, "exact_count_agreement": False}


def test_frozen_artifact_rejects_changed_bytes_before_analysis(tmp_path, monkeypatch):
    path = tmp_path / "source"
    path.write_bytes(b"original")
    expected = {"size_bytes": 8, "sha256": hashlib.sha256(b"original").hexdigest()}
    assert public.verify_artifact(path, expected) == b"original"
    path.write_bytes(b"modified")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        public.verify_artifact(path, expected)
    p = tmp_path / "fcs_files"
    p.mkdir()
    (p / "101_DEN084Y5_15_E01_008_clean.fcs").write_bytes(b"wrong fixture")
    monkeypatch.setattr(public, "AnalysisEngine", lambda: pytest.fail("Analysis began before hash verification"))
    out = tmp_path / "out"
    assert public.main(["--reference-dir", str(tmp_path), "--output", str(out)]) == 2
    assert not out.exists()


def test_extra_fcs_files_are_not_read_by_the_frozen_reference_tool(tmp_path, monkeypatch):
    directory = tmp_path / "fcs_files"
    directory.mkdir()
    (directory / "101_DEN084Y5_15_E01_008_clean.fcs").write_bytes(b"selected")
    (directory / "unrelated.fcs").write_bytes(b"must not analyze")
    monkeypatch.setattr(public, "verify_artifact", lambda *_: pytest.fail("Read input before checking the selected scope"))
    assert public.main(["--reference-dir", str(tmp_path), "--output", str(tmp_path / "out")]) == 2


@pytest.mark.parametrize("accepted, code", [(True, 0), (False, 1)])
def test_cli_returns_nonzero_for_completed_but_failed_qualification(tmp_path, monkeypatch, accepted, code):
    monkeypatch.setattr(public, "qualify", lambda *_: {
        "import_checks": {"source": True}, "count_agreement": {"exact_count_agreement": accepted},
        "qualification_passed": accepted})
    assert public.main(["--reference-dir", str(tmp_path), "--output", str(tmp_path / "out")]) == code
