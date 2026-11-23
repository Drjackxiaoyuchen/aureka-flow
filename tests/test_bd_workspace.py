"""Generated XML/FCS cases; no instrument exports or laboratory data embedded."""
import base64
import io
import json
import zipfile

import flowio
import flowkit as fk
from lxml import etree as E
import numpy as np
import pytest
from fastapi.testclient import TestClient

from aureka_flow import server
from aureka_flow.bd_workspace import DivaWorkspace
from aureka_flow.engine import AnalysisEngine, AxisSpec, ProjectSpec, ViewSpec
from aureka_flow.sessions import SessionStore


def element(parent, tag, text=None, **attrs):
    child = E.SubElement(parent, tag, **attrs)
    if text is not None:
        child.text = str(text)
    return child


def gate(parent, name, ancestry="All Events", *, points=((0, 0), (100, 100)),
         region_type="RECTANGLE_REGION", scaled=False, logged=False, scale=0, y=True):
    g = element(parent, "gate", fullname=ancestry + "\\" + name, type="Region_Classifier")
    for tag, value in [("name", name), ("parent", ancestry), ("input", ancestry), ("enabled", "true"),
                       ("num_events", 0), ("is_x_parameter_scaled", str(scaled).lower()),
                       ("is_y_parameter_scaled", str(scaled).lower()),
                       ("is_x_parameter_log", str(logged).lower()), ("is_y_parameter_log", str(logged).lower()),
                       ("x_parameter_scale_value", scale), ("y_parameter_scale_value", scale)]:
        element(g, tag, value)
    r = element(g, "region", type=region_type, xparm="FITC-A", **({"yparm": "PE-A"} if y else {}))
    pts = element(r, "points")
    for x, yy in points:
        element(pts, "point", x=str(x), y=str(yy))
    return g


def fixture(*, log_gate=False, quadrants=False):
    root = E.Element("bdfacs", version="Version 8.0.1")
    exp = element(root, "experiment", name="Synthetic XML example")
    sheets = element(exp, "acquisition_worksheets")
    gs = element(element(sheets, "worksheet_template", name="Synthetic gates"), "gates")
    source = element(gs, "gate", fullname="All Events", type="EventSource_Classifier")
    element(source, "name", "All Events")
    if log_gate:
        gate(gs, "Signal", points=((1024, 0), (2048, 0)), region_type="INTERVAL_REGION", y=False, scaled=True, logged=True)
    elif quadrants:
        b = element(gs, "gate", fullname="All Events\\divider", type="Composite_Classifier")
        element(b, "parent", "All Events")
        pts = element(element(b, "region", type="BINNER_REGION", xparm="FITC-A", yparm="PE-A"), "points")
        element(pts, "point", x="1", y="1")
        for name, x, y in [("LL", 0, 0), ("LH", 0, 4095), ("HL", 4095, 0), ("HH", 4095, 4095)]:
            element(b, "bin", "All Events\\" + name)
            g = gate(gs, name, points=((1, 1), (x, 1), (x, y), (1, y)), region_type="POLYGON_REGION", scaled=True)
            g.find("input").text = "All Events\\divider"
            g.find("enabled").text = "false"  # quadrant children are driven by their binner
    else:
        gate(gs, "Cells", points=((0, 0), (100, 100)))
        gate(gs, "Child", "All Events\\Cells", points=((9, 0), (29, 0)), region_type="INTERVAL_REGION", y=False)
    specimen = element(exp, "specimen", name="Synthetic specimen")
    tube = element(specimen, "tube", name="Synthetic tube")
    element(tube, "data_filename", "synthetic.fcs")
    element(tube, "data_instrument_name", "Synthetic, not measured")
    settings = element(tube, "instrument_settings")
    element(settings, "compensation_enabled", "true")
    for name, coefficients in [("FITC-A", [1, -0.5]), ("PE-A", [0, 1])]:
        p = element(settings, "parameter", name=name)
        c = element(p, "compensation")
        for value in coefficients:
            element(c, "compensation_coefficient", value)
    return E.tostring(root, encoding="UTF-8", xml_declaration=True)


def fcs(events=None):
    handle = io.BytesIO()
    values = events if events is not None else [[0, 0], [10, 1], [20, 2], [30, 3], [40, 4]]
    flowio.create_fcs(handle, np.asarray(values).ravel().tolist(), ["FITC-A", "PE-A"],
                      metadata_dict={"spillover": "2,FITC-A,PE-A,1,0,0.5,1"})
    return handle.getvalue()


def imported(data=None, **kwargs):
    e = AnalysisEngine()
    info = e.load(fcs(data), "synthetic.fcs")
    doc = DivaWorkspace(fixture(**kwargs), "synthetic.xml")
    e.import_workspace(doc, "global:0", "reconstructed", "xml", True)
    return e, e.record(info["id"]), doc


def test_inverse_compensation_once_and_independent_event_membership():
    e, rec, doc = imported()
    source = rec.sample.get_events(source="raw")
    expected = np.column_stack([source[:, 0] - 0.5 * source[:, 1], source[:, 1]])
    np.testing.assert_allclose(e.events(rec, "xml"), expected)
    np.testing.assert_allclose(e.events(rec, "fcs"), expected)
    assert e.mask(rec, "Child").tolist() == [False, True, True, True, False]
    assert e.populations(rec)[-1]["percent_parent"] == 60
    assert doc.data == fixture()  # extraction never rewrites the source document


def test_logicle_zero_width_reference_and_plot_sampling_are_separate():
    # W=0 inverse has an independent closed-form sinh reference.
    t, m = 262144, 4.5
    lo, hi = [t * np.sinh(m * np.log(10) * q) / np.sinh(m * np.log(10)) for q in (0.25, 0.5)]
    values = np.linspace(-200, 3000, 1000)
    e, rec, _ = imported(np.column_stack([values, np.zeros(1000)]), log_gate=True)
    np.testing.assert_array_equal(e.mask(rec, "Signal"), (values >= lo) & (values < hi))
    view = e.view(ViewSpec(sample_id=rec.uid, x=AxisSpec(channel="FITC-A"), y=AxisSpec(channel="PE-A"),
                           population="Signal", compensation="xml", max_points=100))
    assert view["population_count"] == int(((values >= lo) & (values < hi)).sum())
    assert view["display_count"] == 100
    assert len(set(view["event_indices"])) == 100


def test_quadrants_cover_negative_and_overrange_events_with_disjoint_boundaries():
    # Use source-value mode to independently assert linear divider at 1*64.
    e, rec, doc = imported([[-100, -100], [64, 64], [64, -1], [-1, 64], [1e6, 1e6]], quadrants=True)
    e.import_workspace(doc, "global:0", "reconstructed", "raw", True)
    assert [np.flatnonzero(e.mask(rec, name)).tolist() for name in ("LL", "LH", "HL", "HH")] == [[0], [3], [2], [1, 4]]
    assert np.vstack([e.mask(rec, n) for n in ("LL", "LH", "HL", "HH")]).sum(axis=0).tolist() == [1] * 5


def test_project_and_gatingml_round_trip_membership_and_original_source():
    e, rec, doc = imported()
    project = ProjectSpec.model_validate(json.loads(json.dumps(e.project())))
    replay = AnalysisEngine()
    replay.restore_project(project)  # source may be restored before matching FCS
    uid = replay.load(fcs(), "renamed.fcs")["id"]  # hash binding survives renaming
    assert DivaWorkspace.from_source(replay.workspace["source"]).data == doc.data
    xml, mapping = e.gatingml(rec)
    result = fk.parse_gating_xml(io.BytesIO(xml)).gate_sample(rec.sample)
    for g in e.gates:
        np.testing.assert_array_equal(e.mask(rec, g.name), replay.mask(replay.record(uid), g.name))
        np.testing.assert_array_equal(e.mask(rec, g.name), result.get_gate_membership(mapping[g.name]))
    broken = e.project()
    broken["workspace"]["source"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        ProjectSpec.model_validate(broken)


def test_unknown_version_and_unsupported_gates_are_losslessly_preservable():
    data = fixture().replace(b"Version 8.0.1", b"Version 99")
    doc = DivaWorkspace(data)
    e = AnalysisEngine()
    assert 'workspace' not in e.project()  # ordinary schema 1/2 projects stay backward compatible
    e.import_workspace(doc, "global:0", "preserve", "raw")
    assert e.gates == [] and DivaWorkspace.from_source(e.workspace["source"]).data == data
    with pytest.raises(ValueError, match="supports Diva"):
        doc.gates("global:0", "raw")
    with pytest.raises(ValueError, match="Unsupported region"):
        DivaWorkspace(fixture().replace(b"RECTANGLE_REGION", b"ELLIPSE_REGION")).gates("global:0", "raw")


@pytest.mark.parametrize("data", [b"<bdfacs>", b'<other/>', b'<!DOCTYPE bdfacs [<!ENTITY secret SYSTEM "file:///etc/passwd">]><bdfacs><experiment>&secret;</experiment></bdfacs>'])
def test_invalid_or_external_entity_xml_is_rejected(data):
    with pytest.raises(ValueError):
        DivaWorkspace(data)


def test_no_silent_channel_mapping_ancestry_override_or_cross_sample_application():
    e, rec, _ = imported()
    old = e.project()
    with pytest.raises(ValueError, match="match FCS channels"):
        e.import_workspace(DivaWorkspace(fixture().replace(b'FITC-A', b'Missing-A')), "global:0", "reconstructed", "xml", True)
    assert e.project()["gates"] == old["gates"]
    new = e.load(fcs([[99, 99], [1, 1]]), "another.fcs")
    with pytest.raises(ValueError, match="hash"):
        e.populations(e.record(new["id"]))


def test_pulse_specific_matrix_blocks_and_invalid_shapes():
    root = E.fromstring(fixture())
    settings = root.find('.//instrument_settings')
    for p in list(settings.findall('parameter')):
        h = E.fromstring(E.tostring(p)); h.set('name', p.get('name').replace('-A', '-H')); settings.append(h)
    matrix = DivaWorkspace(E.tostring(root)).matrix(0)
    # Detector order is A,A,H,H here; no A/H mixing.
    np.testing.assert_allclose(matrix.matrix, [[1, 0, 0, 0], [0.5, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0.5, 1]])
    bad = fixture().replace(b'<compensation_coefficient>-0.5', b'<compensation_coefficient>nan')
    with pytest.raises(ValueError, match="non-finite"):
        DivaWorkspace(bad).matrix(0)


def test_api_review_session_isolation_exports_and_budget(monkeypatch):
    monkeypatch.setattr(server, 'sessions', SessionStore())
    with TestClient(server.app) as a, TestClient(server.app) as b:
        uid = a.post('/api/upload', files=[('files', ('synthetic.fcs', fcs()))]).json()['samples'][0]['id']
        source = fixture()
        files = {'file': ('synthetic.xml', source)}
        preview = a.post('/api/workspace/xml/preview', files=files)
        assert preview.status_code == 200 and len(preview.json()['matches']) == 1
        assert a.get('/api/state').json()['gates'] == []
        settings = {'worksheet': 'global:0', 'mode': 'reconstructed', 'compensation': 'xml'}
        assert a.post('/api/workspace/xml', files=files, data=settings).status_code == 422
        result = a.post('/api/workspace/xml', files=files, data=settings | {'acknowledged': 'true'})
        assert result.status_code == 200 and result.json()['gates'] == 2
        assert a.get('/api/workspace/xml').content == source
        assert b.get('/api/workspace/xml').status_code == 422
        assert a.get('/api/metadata/' + uid).json()['xml_detectors'] == ['FITC-A', 'PE-A']
        spec = {'sample_ids': [uid], 'x': {'channel': 'FITC-A'}, 'y': {'channel': 'PE-A'}, 'population': 'Child', 'compensation': 'xml'}
        response = a.post('/api/export/bundle', json=spec)
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            assert z.read('source-workspace.xml') == source
            assert 'gates/sample-01.xml' in z.namelist()
            manifest = json.loads(z.read('manifest.json'))
            assert manifest['gatingml_files'][0]['sample_sha256']
            assert json.loads(z.read('project.json'))['schema_version'] == 3
        from aureka_flow.workflows.browser import experiment_inputs
        from aureka_flow.engine import ComparisonSpec
        live = next(w.engine for w in server.sessions.workspaces.values() if w.engine.samples)
        measurements, _, _ = experiment_inputs(live, ComparisonSpec.model_validate(spec))
        sample = measurements['samples'][0]
        assert 'instrument_gates_reconstructed_not_vendor_count_validated' in sample['qc_flags']
        assert sample['processing']['imported_workspace']['xml_sha256'] == live.workspace['source']['sha256']
        assert sample['processing']['xml_spillover_matrix']
        workspace = next(w for w in server.sessions.workspaces.values() if w.engine.samples)
        assert workspace.input_bytes == len(fcs()) + len(source)
        # Replacing/restoring the XML does not double-charge storage.
        project = a.get('/api/project').json()
        assert a.post('/api/project', json=project).status_code == 200
        assert workspace.input_bytes == len(fcs()) + len(source)
        assert workspace.reserved_bytes == 0
        a.delete('/api/session')
        assert workspace.input_bytes == 0 and workspace.engine.workspace is None


def test_streaming_batch_preserves_sources_membership_and_refuses_overwrite(tmp_path):
    from aureka_flow.diva_batch import analyze_directory
    xml = tmp_path / 'synthetic.xml'
    xml.write_bytes(fixture())
    (tmp_path / 'synthetic.fcs').write_bytes(fcs())
    output = tmp_path / 'results'
    result = analyze_directory(xml, tmp_path, output, acknowledged=True)
    assert result['samples_analyzed'] == 1 and result['population_rows'] == 3 and not result['errors']
    assert (output / 'source-workspace.xml').read_bytes() == xml.read_bytes()
    rows = [json.loads(line) for line in (output / 'membership-ranges.jsonl').read_text(encoding='utf-8').splitlines()]
    assert rows[-1]['population'] == 'Child' and rows[-1]['ranges'] == [[1, 4]]
    assert ProjectSpec.model_validate(json.loads((output / 'aureka-project.json').read_text(encoding='utf-8'))).workspace
    assert 'Reconstructed results' in (output / 'report.html').read_text(encoding='utf-8')
    with pytest.raises(ValueError, match='overwritten'):
        analyze_directory(xml, tmp_path, output, acknowledged=True)
