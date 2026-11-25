"""Ellipse mathematics and atomic independent branch-copy reference cases."""
import io
import json

import flowkit as fk
import numpy as np
import pytest
from fastapi.testclient import TestClient

from aureka_flow import server
from aureka_flow.engine import AnalysisEngine, GateCopySpec, GateEditSpec, GateSpec, ProjectSpec, ViewSpec
from aureka_flow.sessions import SessionStore
from test_analysis import fcs_bytes


def oval(name="Oval", **kwargs):
    return GateSpec(name=name, kind="ellipse", x={"channel": "X"}, y={"channel": "Y"}, bounds=(-4, 4, -2, 2), **kwargs)


def test_ellipse_closed_form_boundary_full_events_and_gatingml():
    x, y = np.meshgrid(np.linspace(-5, 5, 81), np.linspace(-3, 3, 61))
    events = np.concatenate([np.column_stack([x.ravel(), y.ravel()]), [[0, 0], [4, 0], [-4, 0], [0, 2], [0, -2], [4, 2]]])
    engine = AnalysisEngine();uid = engine.load(fcs_bytes(events, ("X", "Y")), "synthetic-ellipse.fcs")["id"]
    engine.add_gate(oval(), uid);rec = engine.record(uid)
    raw = rec.sample.get_events(source="raw")
    expected = (raw[:, 0]/4)**2 + (raw[:, 1]/2)**2 <= 1
    np.testing.assert_array_equal(engine.mask(rec, "Oval"), expected)
    assert engine.mask(rec, "Oval")[-6:].tolist() == [True, True, True, True, True, False]
    view = engine.view(ViewSpec(sample_id=uid, population="Oval", x={"channel": "X"}, y={"channel": "Y"}, max_points=100))
    assert view["display_count"] == 100 and view["population_count"] == expected.sum()
    project = engine.project();assert project["schema_version"] == 5
    with pytest.raises(ValueError, match="schema 5"): ProjectSpec.model_validate(project | {"schema_version": 4})
    engine.restore_project(ProjectSpec.model_validate(project))
    xml, labels = engine.gatingml()
    assert b"EllipsoidGate" in xml
    np.testing.assert_array_equal(fk.parse_gating_xml(io.BytesIO(xml)).gate_sample(rec.sample).get_gate_membership(labels["Oval"]), expected)


def test_transformed_ellipse_uses_saved_coordinates_and_copy_is_independent():
    events = np.column_stack([np.linspace(-100, 50000, 1000), np.linspace(40000, -50, 1000)])
    engine = AnalysisEngine();uid = engine.load(fcs_bytes(events, ("X", "Y")), "synthetic-transformed.fcs")["id"]
    spec = GateSpec(name="Transformed", kind="ellipse", x={"channel": "X", "transform": {"kind": "asinh"}},
                    y={"channel": "Y", "transform": {"kind": "logicle"}}, bounds=(.1, .9, .1, .9))
    engine.add_gate(spec, uid);rec = engine.record(uid)
    x = engine.axis(rec, spec.x, "raw");y = engine.axis(rec, spec.y, "raw")
    expected = ((x-.5)/.4)**2 + ((y-.5)/.4)**2 <= 1
    np.testing.assert_array_equal(engine.mask(rec, spec.name), expected)
    result = engine.copy_gate(spec.name, GateCopySpec(revision=engine.revision, name="Independent"), uid)
    assert result["copied"] == ["Independent"]
    np.testing.assert_array_equal(engine.mask(rec, "Independent"), expected)
    engine.edit_gate("Independent", GateEditSpec(revision=engine.revision, name="Independent", bounds=(.4, .6, .4, .6)), uid)
    np.testing.assert_array_equal(engine.mask(rec, spec.name), expected)
    xml, labels = engine.gatingml()
    results = fk.parse_gating_xml(io.BytesIO(xml)).gate_sample(rec.sample)
    for name in [spec.name, "Independent"]:
        np.testing.assert_array_equal(results.get_gate_membership(labels[name]), engine.mask(rec, name))


@pytest.mark.parametrize("bounds", [(None, 1, 0, 1), (0, 0, 0, 1), (0, 1, 2, 1), (0, 1e308, 0, 1), (0, 1e-300, 0, 1)])
def test_invalid_ellipse_rejected(bounds):
    with pytest.raises(ValueError): GateSpec(name="Invalid", kind="ellipse", x={"channel": "X"}, y={"channel": "Y"}, bounds=bounds)


def branch():
    engine = AnalysisEngine();values = np.arange(1000, dtype=float)
    uid = engine.load(fcs_bytes(np.column_stack([values, values*2]), ("X", "Y")), "synthetic-copy.fcs")["id"]
    for name, parent, lo, hi in [("Cells", "root", 100, 900), ("A", "Cells", 200, 700), ("B", "Cells", 500, 800)]:
        engine.add_gate(GateSpec(name=name, kind="range", parent=parent, x={"channel": "X"}, bounds=(lo, hi, None, None)), uid)
    engine.add_gate(GateSpec(name="Both", kind="boolean", parent="Cells", operation="and", operands=["A", "B"]), uid)
    engine.add_gate(GateSpec(name="Grandchild", parent="Both", kind="range", x={"channel": "X"}, bounds=(550, 650, None, None)), uid)
    return engine, uid


def test_copy_defaults_to_complete_branch_remaps_internal_references_and_undoes_once():
    engine, uid = branch();before = engine._gate_snapshot(engine.gates)
    original = {g.name: engine.mask(engine.record(uid), g.name).copy() for g in engine.gates}
    history = engine.gate_history()["undo"]
    result = engine.copy_gate("Cells", GateCopySpec(revision=engine.revision, name="Reviewed"), uid)
    assert len(result["copied"]) == 5 and engine.gate_history()["undo"] == history+1
    names = result["name_mapping"]
    for name, mask in original.items():
        np.testing.assert_array_equal(engine.mask(engine.record(uid), names[name]), mask)
    copied_both = next(g for g in engine.gates if g.name == names["Both"])
    assert copied_both.operands == [names["A"], names["B"]]
    assert copied_both.parent == "Reviewed"
    engine.edit_gate(names["A"], GateEditSpec(revision=engine.revision, name=names["A"], bounds=(600, 650, None, None)), uid)
    for name, mask in original.items(): np.testing.assert_array_equal(engine.mask(engine.record(uid), name), mask)
    engine.navigate_gate_history("undo", engine.revision)  # edit
    engine.navigate_gate_history("undo", engine.revision)  # whole branch copy
    assert json.loads(engine._gate_snapshot(engine.gates)) == json.loads(before)
    engine.navigate_gate_history("redo", engine.revision)
    assert len(engine.gates) == 10
    xml, labels = engine.gatingml();replay = fk.parse_gating_xml(io.BytesIO(xml)).gate_sample(engine.record(uid).sample)
    for source, target in names.items(): np.testing.assert_array_equal(replay.get_gate_membership(labels[target]), original[source])


def test_copy_one_gate_under_new_parent_recalculates_context_and_names_stay_unique():
    engine, uid = branch()
    result = engine.copy_gate("A", GateCopySpec(revision=engine.revision, name="Restricted", parent="B", include_children=False), uid)
    assert result["copied"] == ["Restricted"]
    np.testing.assert_array_equal(np.flatnonzero(engine.mask(engine.record(uid), "Restricted")), np.arange(500, 700))
    first = engine.copy_gate("Cells", GateCopySpec(revision=engine.revision, name="First"), uid)
    second = engine.copy_gate("Cells", GateCopySpec(revision=engine.revision, name="Second"), uid)
    assert not set(first["copied"]) & set(second["copied"])
    assert all(len(g.name) <= 80 for g in engine.gates)


def test_invalid_copy_duplicate_stale_parent_and_boolean_scope_are_atomic():
    engine, uid = branch()
    for source, values in [("Cells", {"name": "Cells"}), ("Cells", {"name": "New", "parent": "Missing"}),
                            ("Both", {"name": "New", "parent": "root"}), ("Missing", {"name": "New"})]:
        before = (engine.revision, engine._gate_snapshot(engine.gates), engine.gate_history())
        with pytest.raises(ValueError): engine.copy_gate(source, GateCopySpec(revision=engine.revision, **values), uid)
        assert (engine.revision, engine._gate_snapshot(engine.gates), engine.gate_history()) == before
    with pytest.raises(ValueError, match="Refresh"):
        engine.copy_gate("Cells", GateCopySpec(revision=engine.revision-1, name="New"), uid)
    engine.set_gates([GateSpec(name=f"G{i}", kind="range", x={"channel": "X"}, bounds=(0, 1, None, None)) for i in range(100)])
    with pytest.raises(ValueError, match="100 gates"):
        engine.copy_gate("G0", GateCopySpec(revision=engine.revision, name="New"), uid)
    assert len(engine.gates) == 100


def test_copy_api_preserves_project_schema_and_session_isolation(monkeypatch):
    monkeypatch.setattr(server, "sessions", SessionStore())
    with TestClient(server.app) as a, TestClient(server.app) as b:
        uid = a.post('/api/upload', files=[('files', ('synthetic.fcs', fcs_bytes([[0, 0], [1, 1], [2, 2]], ("X", "Y"))))]).json()['samples'][0]['id']
        assert a.post('/api/gates', params={"sample_id": uid}, json=oval().model_dump()).status_code == 200
        revision = a.get('/api/state').json()['gate_history']['revision']
        copied = a.post('/api/gates/Oval/copy', params={"sample_id": uid}, json={"revision": revision, "name": "Oval copy"})
        assert copied.status_code == 200, copied.text
        assert a.get('/api/project').json()['schema_version'] == 5
        assert b.get('/api/state').json()['gates'] == []


def test_copied_instrument_branch_keeps_original_xml_and_compensation_binding():
    from test_bd_workspace import imported
    engine, rec, doc = imported()
    source = engine.workspace['source'].copy()
    original = {g.name: engine.mask(rec, g.name).copy() for g in engine.gates}
    result = engine.copy_gate('Cells', GateCopySpec(revision=engine.revision, name='Reviewed cells'), rec.uid)
    for name, target in result['name_mapping'].items():
        np.testing.assert_array_equal(engine.mask(rec, target), original[name])
    engine.restore_project(ProjectSpec.model_validate(engine.project()))
    assert engine.workspace['source'] == source == doc.source()
    xml, ids = engine.gatingml(rec)
    replay = fk.parse_gating_xml(io.BytesIO(xml)).gate_sample(rec.sample)
    for name, target in result['name_mapping'].items():
        np.testing.assert_array_equal(replay.get_gate_membership(ids[target]), original[name])


def test_long_child_names_get_unique_bounded_copy_names():
    engine, uid = branch()
    name = 'α' * 80
    engine.edit_gate('A', GateEditSpec(revision=engine.revision, name=name), uid)
    first = engine.copy_gate('Cells', GateCopySpec(revision=engine.revision, name='First'), uid)
    second = engine.copy_gate('Cells', GateCopySpec(revision=engine.revision, name='Second'), uid)
    assert len(first['name_mapping'][name]) <= 80 and len(second['name_mapping'][name]) <= 80
    assert first['name_mapping'][name] != second['name_mapping'][name]
