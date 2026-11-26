"""Independent full-event set references, dependency lifecycle and export replay."""
import io
import json
import zipfile
import csv

import flowkit as fk
import numpy as np
import pytest
from fastapi.testclient import TestClient

from aureka_flow import server
from aureka_flow.engine import AnalysisEngine, AxisSpec, ComparisonSpec, GateEditSpec, GateSpec, ProjectSpec, ViewSpec
from aureka_flow.sessions import SessionStore
from aureka_flow.workflows.browser import experiment_inputs
from test_analysis import fcs_bytes


def logic(name, operation, operands, parent="Parent"):
    return GateSpec(name=name, kind="boolean", parent=parent, operation=operation, operands=operands)


def fixture():
    engine = AnalysisEngine()
    for i in range(2):
        x = np.random.default_rng(17 + i).permutation(1000).astype(float)
        events = np.column_stack([x, (x * 7 + i * 13) % 1000])
        uid = engine.load(fcs_bytes(events, ("X", "Y")), f"synthetic-boolean-{i}.fcs")["id"]
    for name, parent, channel, lo, hi in [("Parent", "root", "X", 100, 900),
        ("Expression+", "Parent", "X", 200, 700), ("Binding+", "Parent", "Y", 100, 500)]:
        engine.add_gate(GateSpec(name=name, kind="range", parent=parent, x={"channel": channel}, bounds=(lo, hi, None, None)), uid)
    return engine, uid


def expected(rec):
    x, y = rec.sample.get_events(source="raw").T
    parent = (x >= 100) & (x < 900)
    a, b = parent & (x >= 200) & (x < 700), parent & (y >= 100) & (y < 500)
    return parent, a, b


def test_full_event_boolean_membership_parent_denominators_and_children():
    engine, uid = fixture()
    for name, op, refs in [("Both α+", "and", ["Expression+", "Binding+"]),
        ("Either", "or", ["Expression+", "Binding+"]), ("Not expression", "not", ["Expression+"]),
        ("Nested logic", "or", ["Both α+", "Not expression"])]:
        engine.add_gate(logic(name, op, refs), uid)
    engine.add_gate(GateSpec(name="Child", parent="Nested logic", kind="range", x={"channel": "X"}, bounds=(300, 750, None, None)), uid)
    xml, labels = engine.gatingml()
    replay = fk.parse_gating_xml(io.BytesIO(xml))
    for rec in engine.samples.values():
        p, a, b = expected(rec)
        masks = {"Both α+": a & b, "Either": a | b, "Not expression": p & ~a,
                 "Nested logic": (a & b) | (p & ~a)}
        x = rec.sample.get_events(source="raw")[:, 0]
        masks["Child"] = masks["Nested logic"] & (x >= 300) & (x < 750)
        rows = {row["name"]: row for row in engine.populations(rec)}
        for name, mask in masks.items():
            np.testing.assert_array_equal(engine.mask(rec, name), mask)
            np.testing.assert_array_equal(replay.gate_sample(rec.sample).get_gate_membership(labels[name]), mask)
            denominator = masks["Nested logic"].sum() if name == "Child" else p.sum()
            assert rows[name]["percent_parent"] == pytest.approx(100 * mask.sum() / denominator)
        view = engine.view(ViewSpec(sample_id=rec.uid, population="Either", x={"channel": "X"}, y={"channel": "Y"}, max_points=100))
        assert view["display_count"] == 100 and view["population_count"] == masks["Either"].sum()
        assert view["median_x"] == np.median(x[masks["Either"]])


def test_reference_rename_edit_cache_invalidation_deletion_closure_and_undo():
    engine, uid = fixture()
    engine.add_gate(logic("Both", "and", ["Expression+", "Binding+"]), uid)
    engine.add_gate(logic("Not both", "not", ["Both"]), uid)
    engine.add_gate(GateSpec(name="Child", kind="range", parent="Not both", x={"channel": "X"}, bounds=(0, 1000, None, None)), uid)
    for rec in engine.samples.values(): engine.populations(rec)
    engine.edit_gate("Expression+", GateEditSpec(revision=engine.revision, name="Renamed", bounds=(400, 600, None, None)), uid)
    assert engine.gates[3].operands == ["Renamed", "Binding+"]
    for rec in engine.samples.values():
        p, _, b = expected(rec)
        x = rec.sample.get_events(source="raw")[:, 0]
        np.testing.assert_array_equal(engine.mask(rec, "Both"), b & (x >= 400) & (x < 600))
    engine.edit_gate("Both", GateEditSpec(revision=engine.revision, name="Either", operation="or", operands=["Renamed", "Binding+"]), uid)
    assert engine.gates[4].operands == ["Either"]
    assert engine.delete_gate("Renamed") == ["Child", "Either", "Not both", "Renamed"]
    assert [g.name for g in engine.gates] == ["Parent", "Binding+"]
    engine.navigate_gate_history("undo", engine.revision)
    assert len(engine.gates) == 6
    engine.navigate_gate_history("redo", engine.revision)
    assert len(engine.gates) == 2


def test_not_with_empty_parent_remains_empty_with_explicit_denominator():
    engine, uid = fixture()
    engine.edit_gate("Parent", GateEditSpec(revision=engine.revision, name="Parent", bounds=(2000, 3000, None, None)), uid)
    engine.add_gate(logic("Not A", "not", ["Expression+"]), uid)
    row = engine.populations(engine.record(uid))[-1]
    assert row["count"] == 0 and row["percent_parent"] == 0
    assert not engine.mask(engine.record(uid), "Not A").any()


def test_not_preserves_nonfinite_membership_and_separate_finite_plot_denominators():
    engine = AnalysisEngine()
    events = np.array([[0., 1.], [2., 1.], [np.nan, 1.], [np.inf, 1.],
                       [-np.inf, 1.], [-3., 1.], [2., np.nan]])
    data = fcs_bytes(events, ("X", "Y"))
    uid = engine.load(data, "synthetic-nonfinite-logic.fcs")["id"]
    engine.add_gate(GateSpec(name="Parent", kind="range", x={"channel": "Y"},
                             bounds=(.5, 1.5, None, None)), uid)
    engine.add_gate(GateSpec(name="Positive", parent="Parent", kind="range", x={"channel": "X"},
                             bounds=(1., 3., None, None)), uid)
    engine.add_gate(logic("Not positive", "not", ["Positive"]), uid)
    rec = engine.record(uid)
    expected_indices = [0, 2, 3, 4, 5]
    np.testing.assert_array_equal(np.flatnonzero(engine.mask(rec, "Not positive")), expected_indices)
    row = engine.populations(rec)[-1]
    assert row["count"] == 5 and row["percent_parent"] == pytest.approx(100 * 5 / 6)
    view = engine.view(ViewSpec(sample_id=uid, population="Not positive", x={"channel": "X"}, y={"channel": "Y"}))
    assert view["population_count"] == 5 and view["display_count"] == 2 and view["nonfinite_count"] == 3
    assert view["median_x"] == -1.5
    comparison = ComparisonSpec(sample_ids=[uid], population="Not positive", x={"channel": "X"},
                                y={"channel": "Y"}, histogram_axis="x")
    stats = engine.compare(comparison)["rows"][0]
    assert stats["count"] == 5 and stats["nonfinite_x"] == 3 and stats["nonfinite_y"] == 0
    assert stats["median_x"] == -1.5
    xml, names = engine.gatingml()
    replay = fk.parse_gating_xml(io.BytesIO(xml)).gate_sample(rec.sample)
    np.testing.assert_array_equal(np.flatnonzero(replay.get_gate_membership(names["Not positive"])), expected_indices)
    assert engine.load(data, "same-source.fcs")["sha256"] == rec.digest


def test_geometric_only_project_keeps_legacy_schema_fields():
    engine, _ = fixture()
    project = engine.project()
    assert project["schema_version"] == 2
    assert all("operation" not in gate and "operands" not in gate for gate in project["gates"])
    ProjectSpec.model_validate(project)


def test_operands_keep_distinct_source_and_embedded_compensation_settings():
    engine = AnalysisEngine()
    truth = np.array([[1., 0.], [2., 2.], [3., 4.], [4., 1.]])
    mixing = np.array([[1., .5], [.25, 1.]])
    data = fcs_bytes(truth @ mixing, ("A", "B"), {"spillover": "2,A,B,1,.5,.25,1"})
    uid = engine.load(data, "synthetic-mixed-contexts.fcs")["id"]
    engine.add_gate(GateSpec(name="Source A", kind="range", x={"channel": "A"}, bounds=(3.5, None, None, None)), uid)
    engine.add_gate(GateSpec(name="Compensated B", kind="range", x={"channel": "B"}, compensation="fcs", bounds=(0, 2, None, None)), uid)
    engine.add_gate(logic("Both", "and", ["Source A", "Compensated B"], parent="root"), uid)
    rec = engine.record(uid)
    np.testing.assert_array_equal(np.flatnonzero(engine.mask(rec, "Both")), [3])
    np.testing.assert_allclose(engine.events(rec, "raw"), truth @ mixing)
    xml, labels = engine.gatingml()
    replay = fk.parse_gating_xml(io.BytesIO(xml)).gate_sample(rec.sample)
    np.testing.assert_array_equal(np.flatnonzero(replay.get_gate_membership(labels["Both"])), [3])


@pytest.mark.parametrize("op,refs", [("not", []), ("not", ["Expression+", "Binding+"]),
    ("and", ["Expression+"]), ("or", ["Expression+", "Expression+"])])
def test_bad_arity_or_duplicate_operands_rejected(op, refs):
    with pytest.raises(ValueError): logic("Invalid", op, refs)


@pytest.mark.parametrize("refs,parent", [(["Parent", "Expression+"], "Parent"),
    (["Missing", "Expression+"], "Parent"), (["Invalid", "Expression+"], "Parent"),
    (["Expression+", "Binding+"], "root")])
def test_bad_scope_or_dependencies_fail_without_mutating_strategy(refs, parent):
    engine, uid = fixture()
    before = (engine.revision, engine._gate_snapshot(engine.gates), engine.gate_history())
    with pytest.raises(ValueError): engine.add_gate(logic("Invalid", "and", refs, parent), uid)
    assert (engine.revision, engine._gate_snapshot(engine.gates), engine.gate_history()) == before


def test_cycles_from_edit_and_forward_references_from_project_are_rejected():
    engine, uid = fixture()
    engine.add_gate(logic("Not A", "not", ["Expression+"]), uid)
    engine.add_gate(logic("Both", "and", ["Not A", "Binding+"]), uid)
    before = engine._gate_snapshot(engine.gates)
    with pytest.raises(ValueError, match="cyclic"):
        engine.edit_gate("Not A", GateEditSpec(revision=engine.revision, name="Not A", operands=["Both"]), uid)
    assert engine._gate_snapshot(engine.gates) == before
    gates = engine.gates.copy();gates[3], gates[4] = gates[4], gates[3]
    with pytest.raises(ValueError): engine.set_gates(gates)
    assert engine._gate_snapshot(engine.gates) == before


def test_xml_compensation_transform_context_and_original_source_survive_boolean_roundtrip():
    from test_bd_workspace import imported
    engine, rec, doc = imported()
    engine.add_gate(GateSpec(name="High PE", kind="range", x={"channel": "PE-A"}, compensation="xml", bounds=(20, None, None, None)), rec.uid)
    engine.add_gate(logic("Original and PE", "and", ["Cells", "High PE"], parent="root"), rec.uid)
    source = rec.sample.get_events(source="raw")
    parent_mask = engine.mask(rec, "Cells").copy()
    np.testing.assert_array_equal(engine.mask(rec, "Original and PE"), parent_mask & (source[:, 1] >= 20))
    project = ProjectSpec.model_validate(engine.project())
    assert project.schema_version == 4
    xml, labels = engine.gatingml(rec)
    replay = fk.parse_gating_xml(io.BytesIO(xml))
    np.testing.assert_array_equal(replay.gate_sample(rec.sample).get_gate_membership(labels["Original and PE"]),
                                  engine.mask(rec, "Original and PE"))
    engine.restore_project(project)
    assert doc.source() == engine.workspace["source"]
    np.testing.assert_array_equal(source, rec.sample.get_events(source="raw"))
    engine.add_gate(logic("Empty", "not", ["Original and PE"], parent="root"), rec.uid)
    # NOT is the selected parent's complement, never a separate compensation pass.
    np.testing.assert_array_equal(engine.mask(rec, "Empty"), ~engine.mask(rec, "Original and PE"))


def test_project_gatingml_and_experiment_dependencies_reproduce_source_events():
    engine, uid = fixture()
    engine.add_gate(logic("Both α+", "and", ["Expression+", "Binding+"]), uid)
    project = engine.project()
    assert project["schema_version"] == 4
    assert project["gates"][-1]["compensation"] is None
    with pytest.raises(ValueError, match="schema 4"): ProjectSpec.model_validate(project | {"schema_version": 3})
    replay, _ = fixture()
    replay.restore_project(ProjectSpec.model_validate(project))
    xml, ids = engine.gatingml()
    strategy = fk.parse_gating_xml(io.BytesIO(xml))
    for rec in engine.samples.values():
        _, a, b = expected(rec)
        np.testing.assert_array_equal(strategy.gate_sample(rec.sample).get_gate_membership(ids["Both α+"]), a & b)
        reloaded = next(r for r in replay.samples.values() if r.digest == rec.digest)
        np.testing.assert_array_equal(replay.mask(reloaded, "Both α+"), a & b)
    spec = ComparisonSpec(sample_ids=[uid], population="Both α+", x={"channel": "X"}, y={"channel": "Y"})
    measurements, _, _ = experiment_inputs(engine, spec)
    processing = measurements["samples"][0]["processing"]
    assert [g["name"] for g in processing["gates"]] == ["Parent", "Expression+", "Binding+", "Both α+"]
    assert processing["gates"][-1]["operands"] == ["Expression+", "Binding+"]


def test_boolean_api_project_export_and_session_isolation(monkeypatch):
    engine, uid = fixture()
    store = SessionStore();monkeypatch.setattr(server, "sessions", store)
    with TestClient(server.app) as client:
        client.get('/api/state')
        next(iter(store.workspaces.values())).engine = engine
        response = client.post('/api/gates', params={"sample_id": uid}, json=logic("Both", "and", ["Expression+", "Binding+"]).model_dump())
        assert response.status_code == 200, response.text
        request = {"sample_ids": [uid], "population": "Both", "x": {"channel": "X"}, "y": {"channel": "Y"}}
        response = client.post('/api/export/bundle', json=request)
        assert response.status_code == 200, response.text
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert json.loads(archive.read('project.json'))['schema_version'] == 4
            assert b'BooleanGate' in archive.read('gates.xml')
            path = next(name for name in archive.namelist() if name.startswith('events/'))
            rows = list(csv.DictReader(io.StringIO(archive.read(path).decode('utf-8-sig'))))
            rec = engine.record(uid);_, a, b = expected(rec)
            assert [int(row['event_index_zero_based']) for row in rows] == np.flatnonzero(a & b).tolist()
            assert {row['source_sha256'] for row in rows} == {rec.digest}
        with TestClient(server.app) as other:
            assert other.get('/api/state').json()['gates'] == []


def test_reviewed_delete_rejects_stale_strategy_and_undo_restores_dependencies(monkeypatch):
    engine, uid = fixture()
    store = SessionStore();monkeypatch.setattr(server, "sessions", store)
    with TestClient(server.app) as client:
        client.get('/api/state');next(iter(store.workspaces.values())).engine = engine
        reviewed = engine.revision
        engine.add_gate(logic("Both", "and", ["Expression+", "Binding+"]), uid)
        before = engine._gate_snapshot(engine.gates)
        before_mask = engine.mask(engine.record(uid), "Both").copy()
        response = client.delete('/api/gates/Expression+', params={"revision": reviewed})
        assert response.status_code == 422 and engine._gate_snapshot(engine.gates) == before
        response = client.delete('/api/gates/Expression+', params={"revision": engine.revision})
        assert response.json()["deleted"] == ["Both", "Expression+"]
        engine.navigate_gate_history("undo", engine.revision)
        assert json.loads(engine._gate_snapshot(engine.gates)) == json.loads(before)
        np.testing.assert_array_equal(engine.mask(engine.record(uid), "Both"), before_mask)
