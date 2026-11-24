"""Synthetic analytical references for atomic editing, history and full-event replay."""
import io
import json
import zipfile

import flowkit as fk
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from aureka_flow import server
from aureka_flow.engine import (AnalysisEngine, AxisSpec, GateEditSpec, GateSpec,
                                ProjectSpec, QuadrantsSpec, ViewSpec)
from aureka_flow.sessions import SessionStore
from test_analysis import fcs_bytes
from test_bd_workspace import imported


def interval(name="Parent", parent="root", lower=100, upper=900):
    return GateSpec(name=name, parent=parent, kind="range", x=AxisSpec(channel="X"),
                    bounds=(lower, upper, None, None))


def edit(engine, target, uid, **changes):
    original = next(g for g in engine.gates if g.name == target)
    data = {key: original.model_dump()[key] for key in ("name", "bounds", "vertices")}
    return engine.edit_gate(target, GateEditSpec(revision=engine.revision, **(data | changes)), uid)


def test_edit_parent_recomputes_all_samples_descendants_and_sampling_independent_statistics():
    engine = AnalysisEngine()
    sources = []
    for offset in (0, 50):
        values = np.arange(1200, dtype=float) + offset
        uid = engine.load(fcs_bytes(np.column_stack([values, values * 2]), ("X", "Y")),
                          f"synthetic-{offset}.fcs")["id"]
        sources.append((engine.record(uid), values))
    uid = sources[0][0].uid
    engine.add_gate(interval(), uid)
    engine.add_gate(interval("Child", "Parent", 200, 800), uid)
    engine.add_gate(interval("Grandchild", "Child", 300, 750), uid)
    engine.add_gate(interval("Sibling", "root", 1000, 1100), uid)
    for rec, _ in sources:
        engine.populations(rec)  # prime every sample's results cache before editing
    project = engine.project()
    edit(engine, "Parent", uid, name="Reviewed parent", bounds=(650, 1000, None, None))
    assert engine.gates[1].parent == "Reviewed parent"
    assert engine.gates[2].parent == "Child"
    for rec, values in sources:
        parent = (values >= 650) & (values < 1000)
        child = parent & (values >= 200) & (values < 800)
        grandchild = child & (values >= 300) & (values < 750)
        for name, expected in [("Reviewed parent", parent), ("Child", child), ("Grandchild", grandchild)]:
            np.testing.assert_array_equal(engine.mask(rec, name), expected)
        view = engine.view(ViewSpec(sample_id=rec.uid, population="Child", x=AxisSpec(channel="X"),
                                    y=AxisSpec(channel="Y"), max_points=100))
        assert view["display_count"] == 100
        assert view["population_count"] == 150
        assert view["median_x"] == np.median(values[child])
        rows = {p["name"]: p for p in view["populations"]}
        assert rows["Grandchild"]["percent_parent"] == pytest.approx(100 * grandchild.sum() / child.sum())
        np.testing.assert_array_equal(engine.mask(rec, "Sibling"), (values >= 1000) & (values < 1100))
    assert [s["sha256"] for s in project["samples"]] == [s["sha256"] for s in engine.project()["samples"]]
    engine.navigate_gate_history("undo", engine.revision)
    for rec, values in sources:
        np.testing.assert_array_equal(engine.mask(rec, "Grandchild"), (values >= 300) & (values < 750))
    engine.navigate_gate_history("redo", engine.revision)
    assert engine.gates[0].name == "Reviewed parent"
    xml, labels = engine.gatingml()
    replay = fk.parse_gating_xml(io.BytesIO(xml))
    for rec, _ in sources:
        np.testing.assert_array_equal(replay.gate_sample(rec.sample).get_gate_membership(labels["Grandchild"]),
                                      engine.mask(rec, "Grandchild"))


def test_polygon_edit_uses_independent_triangle_reference_and_rectangle_open_bounds():
    engine = AnalysisEngine()
    xx, yy = np.meshgrid(np.arange(-3, 7) + .25, np.arange(-3, 7) + .25)
    events = np.column_stack([xx.ravel(), yy.ravel()])
    uid = engine.load(fcs_bytes(events, ("X", "Y")), "synthetic-grid.fcs")["id"]
    engine.add_gate(GateSpec(name="Box", kind="rectangle", x={"channel": "X"}, y={"channel": "Y"},
                             bounds=(-2, 5, -2, 5)), uid)
    engine.add_gate(GateSpec(name="Triangle", parent="Box", kind="polygon", x={"channel": "X"}, y={"channel": "Y"},
                             vertices=[(-2, -2), (5, -2), (-2, 5)]), uid)
    edit(engine, "Triangle", uid, vertices=[(.01, .01), (6.29, .01), (.01, 6.29)])
    edit(engine, "Box", uid, bounds=(None, 6, 0, None))
    expected = ((events[:, 0] >= .01) & (events[:, 1] >= .01) &
                (events[:, 0] + events[:, 1] < 6.30) & (events[:, 0] < 6))
    np.testing.assert_array_equal(engine.mask(engine.record(uid), "Triangle"), expected)


def test_invalid_and_stale_edits_are_atomic_and_new_change_clears_redo():
    engine = AnalysisEngine()
    uid = engine.load(fcs_bytes([[0, 0], [1, 1]], ("X", "Y")), "synthetic.fcs")["id"]
    engine.add_gate(interval(lower=0, upper=2), uid)
    engine.add_gate(interval("Other", lower=0, upper=1), uid)
    before = engine.project()["gates"], engine.gate_history()
    for data in [dict(name="Other"), dict(bounds=(2, 1, None, None)),
                 dict(name="root"), dict(vertices=[(0, 0), (1, 0), (0, 1)])]:
        with pytest.raises(ValueError):
            edit(engine, "Parent", uid, **data)
        assert (engine.project()["gates"], engine.gate_history()) == before
    with pytest.raises(ValueError, match="changed"):
        engine.edit_gate("Parent", GateEditSpec(revision=engine.revision - 1, name="Parent",
                                               bounds=(0, 1, None, None)), uid)
    engine.navigate_gate_history("undo", engine.revision)
    assert engine.gate_history()["redo"] == 1
    edit(engine, "Parent", uid, bounds=(None, 1, None, None))
    assert engine.gate_history()["redo"] == 0
    with pytest.raises(ValueError, match="No gate change"):
        engine.navigate_gate_history("redo", engine.revision)


def test_subtree_delete_and_quadrants_are_single_undoable_actions():
    engine = AnalysisEngine()
    uid = engine.load(fcs_bytes([[0, 0], [1, 1]], ("X", "Y")), "synthetic.fcs")["id"]
    engine.add_gate(interval(lower=0, upper=2), uid)
    engine.add_quadrants(QuadrantsSpec(sample_id=uid, parent="Parent", x={"channel": "X"}, y={"channel": "Y"},
                                     expression_threshold=.5, binding_threshold=.5))
    saved = engine.project()["gates"]
    engine.navigate_gate_history("undo", engine.revision)
    assert len(engine.gates) == 1
    engine.navigate_gate_history("redo", engine.revision)
    engine.delete_gate("Parent")
    assert engine.gates == []
    engine.navigate_gate_history("undo", engine.revision)
    assert engine.project()["gates"] == saved


def test_history_limits_noop_and_definition_snapshot_isolation(monkeypatch):
    engine = AnalysisEngine()
    uid = engine.load(fcs_bytes([[0, 0], [1, 1]], ("X", "Y")), "synthetic.fcs")["id"]
    spec = interval(lower=0, upper=2)
    engine.add_gate(spec, uid)
    spec.bounds = (10, 20, None, None)
    assert engine.gates[0].bounds == (0, 2, None, None)
    before = engine.gate_history()
    edit(engine, "Parent", uid)  # no-op must not consume an undo step or invalidate other editors
    assert engine.gate_history() == before
    for upper in range(3, 29):
        edit(engine, "Parent", uid, bounds=(0, upper, None, None))
    assert engine.gate_history()["undo"] == engine.GATE_HISTORY_STEPS
    for _ in range(engine.GATE_HISTORY_STEPS):
        engine.navigate_gate_history("undo", engine.revision)
    assert engine.gate_history()["undo"] == 0
    assert engine.gate_history()["redo"] == engine.GATE_HISTORY_STEPS
    monkeypatch.setattr(engine, "GATE_HISTORY_BYTES", 1000)
    edit(engine, "Parent", uid, bounds=(0, 100, None, None))
    assert sum(map(len, engine._gate_undo + engine._gate_redo)) <= 1000
    assert engine.gate_history()["redo"] == 0


def test_xml_source_compensation_transforms_and_project_replay_are_preserved():
    engine, rec, doc = imported(log_gate=True)
    source = engine.project()["workspace"]
    original = engine.gates[0].model_dump()
    gate = engine.gates[0]
    edit(engine, gate.name, rec.uid, bounds=(.1, .9, None, None))
    changed = engine.gates[0].model_dump()
    for key in ("x", "y", "compensation", "parent", "kind"):
        assert changed[key] == original[key]
    assert engine.project()["workspace"] == source
    raw = rec.sample.get_events(source="raw")
    np.testing.assert_allclose(engine.events(rec, "xml")[:, 0], raw[:, 0] - .5 * raw[:, 1])
    expected = engine.mask(rec, gate.name).copy()
    project = ProjectSpec.model_validate(engine.project())
    engine.restore_project(project)
    assert engine.gate_history()["undo"] == engine.gate_history()["redo"] == 0
    np.testing.assert_array_equal(engine.mask(rec, gate.name), expected)
    assert engine.project()["workspace"]["source"] == doc.source()
    edit(engine, gate.name, rec.uid, bounds=(.2, .8, None, None))
    engine.import_workspace(doc, "global:0", "reconstructed", "xml", True)
    assert engine.gate_history()["undo"] == 0
    assert engine.gates[0].model_dump() == original


def test_api_edits_history_session_isolation_and_event_bundle(monkeypatch):
    monkeypatch.setattr(server, "sessions", SessionStore())
    with TestClient(server.app) as a, TestClient(server.app) as b:
        uid = a.post('/api/upload', files=[('files', ('synthetic.fcs', fcs_bytes(
            [[0, 0], [1, 2], [2, 4], [3, 6], [4, 8]], ("X", "Y"))))]).json()["samples"][0]["id"]
        a.post('/api/gates', params={"sample_id": uid}, json=interval(lower=0, upper=5).model_dump())
        a.post('/api/gates', params={"sample_id": uid}, json=interval("Child", "Parent", 1, 4).model_dump())
        revision = a.get('/api/state').json()['gate_history']['revision']
        payload = {"revision": revision, "name": "Reviewed", "bounds": [2, 5, None, None]}
        assert a.put('/api/gates/Parent', params={"sample_id": uid}, json=payload).json()['count'] == 3
        assert a.put('/api/gates/Parent', params={"sample_id": uid}, json=payload).status_code == 422
        assert b.get('/api/state').json()['gate_history']['undo'] == 0
        assert b.post('/api/gate-history/undo', json={"revision": 0}).status_code == 422
        view = {"sample_id": uid, "population": "Child", "x": {"channel": "X"}, "y": {"channel": "Y"}}
        assert a.post('/api/view', json=view).json()['population_count'] == 2
        bundle = a.post('/api/export/bundle', json={k: v for k, v in view.items() if k != 'sample_id'} | {"sample_ids": [uid]})
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            events = pd.read_csv(io.BytesIO(archive.read('events/01_synthetic.csv')))
            assert events['event_index_zero_based'].tolist() == [2, 3]
            assert json.loads(archive.read('project.json'))['gates'][1]['parent'] == 'Reviewed'
            assert set(events['source_sha256']) == {a.get('/api/state').json()['samples'][0]['sha256']}
        revision = a.get('/api/state').json()['gate_history']['revision']
        assert a.post('/api/gate-history/undo', json={"revision": revision}).status_code == 200
        assert a.post('/api/view', json=view).json()['population_count'] == 3
        revision = a.get('/api/state').json()['gate_history']['revision']
        assert a.post('/api/gate-history/redo', json={"revision": revision}).status_code == 200
        assert a.post('/api/view', json=view).json()['population_count'] == 2
        assert a.put('/api/gates/Reviewed', params={"sample_id": uid}, json=payload | {"revision": revision + 1, "parent": "Child"}).status_code == 422
        a.delete('/api/session')
        assert a.get('/api/state').json()['gate_history']['undo'] == 0
