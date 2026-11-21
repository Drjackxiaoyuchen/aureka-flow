"""Synthetic FCS fixtures exercise import safeguards, not BD hardware validation."""
import hashlib
import io
import json
import zipfile

import flowio
import numpy as np
import pytest
from fastapi.testclient import TestClient

from aureka_flow import server
from aureka_flow.engine import AnalysisEngine
from aureka_flow.sessions import SessionStore


EVENTS = np.array([[30., 6.], [10., 2.], [20., 4.]])
SPILL = "2,FITC-A,APC-A,1,0.1,0.2,1"


def fixture(metadata):
    handle = io.BytesIO()
    flowio.create_fcs(handle, EVENTS.ravel().tolist(), ["FITC-A", "APC-A"],
                      opt_channel_names=["Reporter", "Reporter"], metadata_dict=metadata)
    return handle.getvalue()


@pytest.mark.parametrize("keyword", ["spill", "spillover"])
def test_source_metadata_channel_mapping_and_event_order_survive(keyword):
    data = fixture({keyword: SPILL, "cyt": "FACSMelody", "creator": "synthetic Chorus-like fixture",
                    "date": "21-NOV-2026", "btim": "09:00:00", "etim": "09:01:00"})
    engine = AnalysisEngine()
    info = engine.load(data, "synthetic.fcs")
    rec = engine.record(info["id"])
    review = info["import_review"]
    assert review["source_reported"]["cyt"] == "FACSMelody"
    assert review["source_reported"]["creator"] == "synthetic Chorus-like fixture"
    assert review["source_compensation_state"] == "unverified"
    assert review["embedded_matrix_keywords"] == [keyword]
    assert review["embedded_matrix_status"] == "usable"
    assert [c["parameter_number"] for c in info["channels"]] == [1, 2]
    assert [c["id"] for c in info["channels"]] == ["FITC-A", "APC-A"]
    assert [c["stain"] for c in info["channels"]] == ["Reporter", "Reporter"]
    assert info["sha256"] == hashlib.sha256(data).hexdigest()
    np.testing.assert_array_equal(engine.events(rec, "raw"), EVENTS)
    expected = np.linalg.solve(np.array([[1., .1], [.2, 1.]]).T, EVENTS.T).T
    np.testing.assert_allclose(engine.events(rec, "fcs"), expected)
    assert engine.project()["samples"][0]["import_review"] == review


@pytest.mark.parametrize("metadata, error", [
    ({"spill": SPILL, "spillover": "2,FITC-A,APC-A,1,0,0,1"}, "Conflicting"),
    ({"spillover": "2,FITC-A,APC-A,1,nan,0,1"}, "non-finite"),
    ({"spillover": "2,FITC-A,APC-A,1,inf,0,1"}, "non-finite"),
    ({"spillover": "2,FITC-A,APC-A,1,1,1,1"}, ""),
    ({"spillover": "broken"}, ""),
])
def test_unusable_matrix_cannot_change_source_or_enable_compensated_analysis(metadata, error):
    engine = AnalysisEngine()
    info = engine.load(fixture(metadata), "unusable.fcs")
    rec = engine.record(info["id"])
    assert not info["compensation_available"]
    assert info["import_review"]["embedded_matrix_status"] == "unusable"
    assert info["compensation_error"]
    assert error in info["compensation_error"]
    np.testing.assert_array_equal(engine.events(rec, "raw"), EVENTS)
    with pytest.raises(ValueError, match="No usable embedded spillover"):
        engine.events(rec, "fcs")


def test_identical_numeric_matrices_are_not_a_false_conflict():
    engine = AnalysisEngine()
    info = engine.load(fixture({"spill": SPILL, "spillover": "2,FITC-A,APC-A,1.0,0.10,0.20,1.0"}), "same.fcs")
    assert info["compensation_available"]
    assert info["compensation_error"] is None


def test_missing_metadata_is_unknown_not_an_uncompensated_claim():
    info = AnalysisEngine().load(fixture({}), "unknown.fcs")
    assert info["import_review"]["source_reported"]["cyt"] is None
    assert info["import_review"]["embedded_matrix_status"] == "missing"
    assert info["import_review"]["source_compensation_state"] == "unverified"


def test_import_review_and_matrix_failure_are_visible_in_api_and_bundle(monkeypatch):
    monkeypatch.setattr(server, "sessions", SessionStore())
    with TestClient(server.app) as client:
        uploaded = client.post("/api/upload", files=[("files", ("conflict.fcs", fixture({
            "cyt": "FACSMelody", "spill": SPILL, "spillover": "2,FITC-A,APC-A,1,0,0,1"})))])
        info = uploaded.json()["samples"][0]
        uid = info["id"]
        assert client.get("/api/state").json()["samples"][0]["import_review"] == info["import_review"]
        assert client.get(f"/api/metadata/{uid}").json()["spillover_matrix"] is None
        spec = {"sample_id": uid, "x": {"channel": "FITC-A"}, "y": {"channel": "APC-A"}, "compensation": "fcs"}
        rejected = client.post("/api/view", json=spec)
        assert rejected.status_code == 422 and "Conflicting" in rejected.json()["detail"]
        bundle = client.post("/api/export/bundle?include_events=false", json={
            "sample_ids": [uid], "x": {"channel": "FITC-A"}, "y": {"channel": "APC-A"}, "compensation": "raw"})
        assert bundle.status_code == 200
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            assert "gates.xml" not in archive.namelist()
            assert json.loads(archive.read("manifest.json"))["gatingml_included"] is False
            sample = json.loads(archive.read("project.json"))["samples"][0]
            assert sample["import_review"] == info["import_review"]
            assert sample["fcs_metadata"]["spill"] == SPILL
        rejected = client.get("/api/gatingml", params={"sample_id": uid})
        assert rejected.status_code == 422 and "Save at least one" in rejected.json()["detail"]
