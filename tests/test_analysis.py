"""Known event fixtures verify scientific calculations, exports and failure handling."""
import io
import json

import flowio
import flowkit as fk
import numpy as np
import pytest
from fastapi.testclient import TestClient

from aureka_flow.engine import AnalysisEngine, AxisSpec, ComparisonSpec, GateSpec, ProjectSpec, QuadrantsSpec, TransformSpec, ViewSpec
from aureka_flow import server
from aureka_flow.sessions import SessionStore


def fcs_bytes(events, channels=("EXPR-A", "BIND-A"), metadata=None):
    buffer = io.BytesIO()
    flowio.create_fcs(buffer, np.asarray(events, dtype=float).ravel().tolist(), list(channels), metadata_dict=metadata)
    return buffer.getvalue()


@pytest.fixture
def dataset():
    events = np.array([[0, 0], [1, 1], [2, 2], [3, 3], [4, 4], [5, 0], [0, 5], [5, 5]], dtype=float)
    engine = AnalysisEngine()
    info = engine.load(fcs_bytes(events), "known.fcs")
    return engine, info["id"], events


def axes(kind="linear"):
    transform = TransformSpec(kind=kind)
    return AxisSpec(channel="EXPR-A", transform=transform), AxisSpec(channel="BIND-A", transform=transform)


def gate(name="Cells", parent="root", bounds=(1, 5, 1, 5), kind="linear"):
    x, y = axes(kind)
    return GateSpec(name=name, parent=parent, kind="rectangle", x=x, y=y, bounds=bounds)


def test_rectangle_boundaries_nested_denominators_and_delete(dataset):
    engine, uid, events = dataset
    assert engine.add_gate(gate(), uid)["count"] == 4  # inclusive lower, exclusive upper
    assert engine.add_gate(gate("Child", "Cells", (2, 4, 2, 4)), uid)["count"] == 2
    pops = engine.populations(engine.record(uid))
    assert pops[-1]["percent_total"] == 25
    assert pops[-1]["percent_parent"] == 50
    engine.delete_gate("Cells")
    assert engine.gates == []


@pytest.mark.parametrize("kind", ["logicle", "asinh"])
def test_transform_coordinates_match_gate_calculations(dataset, kind):
    engine, uid, events = dataset
    x, y = axes(kind)
    transform = x.transform.build()
    limits = transform.apply(np.array([1., 5.])).tolist()
    spec = GateSpec(name="Transformed", kind="rectangle", x=x, y=y, bounds=[*limits, *limits])
    engine.add_gate(spec, uid)
    assert engine.mask(engine.record(uid), "Transformed").tolist() == [False, True, True, True, True, False, False, False]
    v = engine.view(ViewSpec(sample_id=uid, x=x, y=y))
    assert v["median_x"] == pytest.approx(np.median(transform.apply(events[:, 0].copy())))


def test_polygon_membership_uses_full_events(dataset):
    engine, uid, events = dataset
    x, y = axes()
    engine.add_gate(GateSpec(name="Polygon", kind="polygon", x=x, y=y, vertices=[(-1,-1),(6,-1),(6,6),(-1,6)]), uid)
    assert engine.mask(engine.record(uid), "Polygon").sum() == len(events)


def test_empty_parent_and_nonfinite_display_values(dataset):
    engine, uid, _ = dataset
    engine.add_gate(gate("Empty",bounds=(20,30,20,30)),uid)
    engine.add_gate(gate("Empty child",parent="Empty",bounds=(21,29,21,29)),uid)
    pop=engine.populations(engine.record(uid))[-1]
    assert pop['count'] == 0 and pop['percent_parent'] == 0
    x,y=axes()
    view=engine.view(ViewSpec(sample_id=uid,x=x,y=y,population='Empty'))
    assert view['median_y'] is None and view['display_count'] == 0
    rec=engine.record(uid)
    rec.sample.get_events(source='raw')[0,0]=np.nan
    view=engine.view(ViewSpec(sample_id=uid,x=x,y=y))
    assert view['nonfinite_count'] == 1 and view['population_count'] == 8 and view['display_count'] == 7


def test_histogram_defaults_to_binding_y_and_can_show_expression_x():
    engine=AnalysisEngine()
    uid=engine.load(fcs_bytes([[1,100],[2,200],[3,300]]),'different_scales.fcs')['id']
    x,y=axes()
    spec=ComparisonSpec(sample_ids=[uid],x=x,y=y)
    hist=engine.compare(spec)['histograms'][0]
    assert min(hist['x']) >= 100 and max(hist['x']) <= 300
    hist=engine.compare(spec.model_copy(update={'histogram_axis':'x'}))['histograms'][0]
    assert min(hist['x']) >= 1 and max(hist['x']) <= 3


def test_subsample_does_not_change_counts():
    events = np.column_stack([np.arange(1000), np.arange(1000)])
    engine = AnalysisEngine(); uid = engine.load(fcs_bytes(events), "large.fcs")["id"]
    engine.add_gate(gate(bounds=(100, 900, 100, 900)), uid)
    x, y = axes()
    view = engine.view(ViewSpec(sample_id=uid, x=x, y=y, population="Cells", max_points=100))
    assert view["display_count"] == 100
    assert view["population_count"] == 800
    assert view["median_x"] == 499.5


def test_quadrants_partition_parent_and_expression_positive(dataset):
    engine, uid, events = dataset; x, y = axes()
    engine.add_quadrants(QuadrantsSpec(sample_id=uid, x=x, y=y, expression_threshold=2, binding_threshold=2))
    rec = engine.record(uid)
    masks = [engine.mask(rec, g.name) for g in engine.gates[:4]]
    assert np.all(np.sum(masks, axis=0) == 1)
    assert engine.mask(rec, "YSD Expression+").tolist() == (events[:, 0] >= 2).tolist()
    assert engine.mask(rec, "YSD E+ B+")[2]  # equality is positive
    summary = engine.compare(ComparisonSpec(sample_ids=[uid], x=x, y=y, population="YSD Expression+"))
    assert summary["rows"][0]["median_y"] == 3
    assert sum(summary["histograms"][0]["percent"]) == pytest.approx(100)


def test_compensation_and_gates_agree():
    events = np.array([[10., 2.], [20., 4.], [30., 6.]])
    metadata = {"spillover": "2,EXPR-A,BIND-A,1,0.1,0.2,1"}
    engine = AnalysisEngine(); uid = engine.load(fcs_bytes(events, metadata=metadata), "spill.fcs")["id"]
    rec = engine.record(uid)
    expected = np.linalg.solve(np.array([[1,.1],[.2,1]]).T, events.T).T
    assert np.allclose(engine.events(rec, "fcs"), expected)
    x, y = axes(); limits = [float(expected[0,0]-.1),float(expected[1,0]+.1),-100.,100.]
    engine.add_gate(GateSpec(name="Compensated",kind="rectangle",x=x,y=y,compensation="fcs",bounds=limits),uid)
    assert engine.mask(rec,"Compensated").tolist() == [True,True,False]


def test_missing_compensation_and_channels_never_fall_back(dataset):
    engine, uid, events = dataset; x, y = axes()
    with pytest.raises(ValueError, match="spillover"):
        engine.view(ViewSpec(sample_id=uid,x=x,y=y,compensation="fcs"))
    engine.add_gate(gate(), uid)
    other = engine.load(fcs_bytes(events,channels=("OTHER-A","BIND-A")), "other.fcs")["id"]
    rows = engine.compare(ComparisonSpec(sample_ids=[uid,other],x=x,y=y,population="Cells"))["rows"]
    assert rows[0]["count"] == 4
    assert "missing channel" in rows[1]["error"]


def test_invalid_strategy_is_atomic_and_duplicate_file_is_deduplicated(dataset):
    engine, uid, events = dataset
    engine.add_gate(gate(),uid)
    with pytest.raises(ValueError,match="Duplicate"):
        engine.add_gate(gate(),uid)
    assert len(engine.gates) == 1
    project=ProjectSpec.model_validate(engine.project())
    assert project.samples[0]["sha256"] == engine.record(uid).digest
    assert len(project.gates) == 1
    assert engine.load(fcs_bytes(events),"renamed.fcs")["id"] == uid
    assert len(engine.samples) == 1


def test_gatingml_roundtrip_for_readable_labels_and_nested_gates(dataset):
    engine, uid, _ = dataset; x, y = axes("logicle")
    engine.add_gate(gate(name="Yeast singlets"),uid)
    engine.add_quadrants(QuadrantsSpec(sample_id=uid,parent="Yeast singlets",x=x,y=y,
                                      expression_threshold=.12,binding_threshold=.12))
    xml, mapping = engine.gatingml()
    imported=fk.parse_gating_xml(io.BytesIO(xml))
    result=imported.gate_sample(engine.record(uid).sample)
    for g in engine.gates:
        assert np.array_equal(result.get_gate_membership(mapping[g.name]),engine.mask(engine.record(uid),g.name))


def test_api_upload_gating_exports_and_errors(dataset, monkeypatch):
    engine, uid, events = dataset
    monkeypatch.setattr(server,"sessions",SessionStore(factory=lambda:engine))
    client=TestClient(server.app)
    assert client.get('/').status_code == 200
    bad=client.post('/api/upload',files=[('files',('invalid.fcs',b'not FCS'))]).json()
    assert bad['errors'] and not bad['samples']
    g=gate().model_dump()
    response=client.post('/api/gates',params={'sample_id':uid},json=g)
    assert response.status_code == 200 and response.json()['count'] == 4
    x,y=axes();v=ViewSpec(sample_id=uid,x=x,y=y,population='Cells').model_dump()
    assert client.post('/api/view',json=v).json()['population_count'] == 4
    csv=client.post('/api/export/events',json=v)
    import pandas as pd
    frame=pd.read_csv(io.StringIO(csv.text))
    assert len(frame) == 4 and frame['event_index_zero_based'].tolist() == [1,2,3,4]
    assert frame['source_sha256'].iloc[0] == engine.record(uid).digest
    comparison=ComparisonSpec(sample_ids=[uid],x=x,y=y,population='Cells').model_dump()
    summary=client.post('/api/export/stats',json=comparison)
    assert pd.read_csv(io.StringIO(summary.text))['count'].iloc[0] == 4
    xml=client.get('/api/gatingml',params={'sample_id':uid})
    assert len(fk.parse_gating_xml(io.BytesIO(xml.content)).get_gate_ids()) == 1
    project=client.get('/api/project').json()
    assert client.post('/api/project',json=project).status_code == 200
    assert client.post('/api/view',json={**v,'compensation':'fcs'}).status_code == 422
    invalid={**g,'bounds':[5,1,1,5]}
    assert client.post('/api/gates',params={'sample_id':uid},json=invalid).status_code == 422


def test_demo_is_self_contained_deterministic_and_labeled(monkeypatch):
    engine = AnalysisEngine()
    monkeypatch.setattr(server, 'sessions', SessionStore(factory=lambda:engine))
    client = TestClient(server.app)
    first = client.post('/api/demo').json()['samples']
    second = client.post('/api/demo').json()['samples']
    assert len(engine.samples) == 3
    assert [s['sha256'] for s in first] == [s['sha256'] for s in second]
    assert all(s['events'] == 30000 and 'Synthetic' in s['origin'] for s in first)
    body = {'sample_id': first[0]['id'], 'x': {'channel':'Expression-A'},
            'y': {'channel':'Binding-A'}, 'max_points':200}
    result = client.post('/api/view', json=body)
    assert result.status_code == 200
    assert result.json()['population_count'] == 30000 and result.json()['display_count'] == 200


def test_validation_landing_works_without_private_reports(monkeypatch, tmp_path):
    monkeypatch.setattr(server, 'VALIDATION_DIR', tmp_path)
    client = TestClient(server.app)
    response = client.get('/validation/')
    assert response.status_code == 200
    assert 'Upload FCS files' in response.text
    assert 'validate_workspace.py' in response.text
