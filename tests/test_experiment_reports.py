"""Browser-to-workflow handoff checked against known original-event indices."""
import hashlib
import io
import json
import zipfile

import flowio
import numpy as np
import pytest
from fastapi.testclient import TestClient

from aureka_flow import server
from aureka_flow.engine import AnalysisEngine, AxisSpec, ComparisonSpec, GateSpec, TransformSpec
from aureka_flow.sessions import SessionStore
from aureka_flow.workflows.browser import acquisition_qc, experiment_inputs, manifest_template


def fcs(offset=0):
    buffer = io.BytesIO()
    values = [[0, 8, 0], [1, -1, 1], [2, 2, .5], [3, 4, 3], [4, np.nan, 4], [5, 10, 5]]
    values[0][1] += offset
    flowio.create_fcs(buffer, np.asarray(values).ravel().tolist(), ['X', 'Y', 'Time'],
                      metadata_dict={'TIMESTEP': '1', 'BTIM': '12:00:00', 'ETIM': '12:00:05'})
    return buffer.getvalue()


@pytest.fixture
def known():
    engine = AnalysisEngine()
    uid = engine.load(fcs(), 'known.fcs')['id']
    transform = TransformSpec(kind='asinh')
    x = AxisSpec(channel='X', transform=transform)
    low, high = transform.build().apply(np.array([1., 5.]))
    engine.add_gate(GateSpec(name='Parent', kind='range', x=x, bounds=[low, high, None, None]), uid)
    engine.add_gate(GateSpec(name='Child', parent='Parent', kind='range',
                             x=AxisSpec(channel='X'), bounds=[2, 5, None, None]), uid)
    spec = ComparisonSpec(sample_ids=[uid], x=x, y=AxisSpec(channel='Y'), population='Child')
    return engine, uid, spec


def test_exact_membership_linear_summary_and_acquisition_wide_qc(known):
    engine, uid, spec = known
    measured, manifest, experiment = experiment_inputs(engine, spec)
    sample = measured['samples'][0]
    assert sample['sample_id'] == hashlib.sha256(fcs()).hexdigest()
    assert sample['event_count'] == 6 and sample['selected_count'] == 3
    assert sample['processing']['selected_event_ranges'] == [[2, 5]]
    assert [gate['name'] for gate in sample['processing']['gates']] == ['Parent', 'Child']
    assert sample['processing']['gates'][0]['x']['transform']['kind'] == 'asinh'
    assert sample['channels']['X']['median'] == 3  # independent of display transform
    assert sample['channels']['Y'] == {'median': 3, 'finite_count': 2, 'negative_count': 0}
    assert manifest['samples'][0]['biological_replicate'] is None
    assert experiment['comparison_status'] == 'metadata_limited'
    assert 'finite_denominator_differs' in {w['code'] for w in experiment['warnings']}
    qc = acquisition_qc(engine.record(uid))
    assert qc['event_count'] == 6 and qc['time']['backward_steps'] == 1
    assert qc['time']['time_span_seconds'] == 5
    assert qc['nonfinite_counts']['Y'] == 1 and not qc['automatic_event_exclusion']


def test_metadata_is_explicit_and_cross_batch_restrictions_survive(known):
    engine, _, spec = known
    other = engine.load(fcs(1), 'other.fcs')['id']
    spec = spec.model_copy(update={'sample_ids': spec.sample_ids + [other]})
    manifest = manifest_template(engine, spec)
    for i, row in enumerate(manifest['samples']):
        row.update(condition=f'condition-{i}', biological_replicate='bio-1', batch_id=f'batch-{i}')
    experiment = experiment_inputs(engine, spec, manifest)[2]
    assert experiment['comparison_status'] == 'cross_batch_blocked'
    assert 'condition_batch_confounding' in {w['code'] for w in experiment['warnings']}
    assert [row['declared_biological_replicate_count'] for row in experiment['condition_summaries']] == [1, 1]
    manifest['samples'][0]['sample_id'] = 'wrong-source'
    with pytest.raises(ValueError, match='sample_id join'):
        experiment_inputs(engine, spec, manifest)


def test_duplicate_missing_and_mixed_sources_reject(known):
    engine, uid, spec = known
    with pytest.raises(ValueError, match='each sample once'):
        experiment_inputs(engine, spec.model_copy(update={'sample_ids': [uid, uid]}))
    other = engine.load(fcs(2), 'demo.fcs', 'Synthetic demo · simulated signals, not experimental data')['id']
    with pytest.raises(ValueError, match='synthetic demo samples or uploaded'):
        experiment_inputs(engine, spec.model_copy(update={'sample_ids': [uid, other]}))
    with pytest.raises(ValueError, match='missing'):
        experiment_inputs(engine, spec.model_copy(update={'x': AxisSpec(channel='MISSING')}))
    with pytest.raises(ValueError, match='No usable embedded'):
        experiment_inputs(engine, spec.model_copy(update={'compensation': 'fcs'}))


def test_experiment_zip_is_offline_hash_checked_and_session_scoped(monkeypatch):
    monkeypatch.setattr(server, 'sessions', SessionStore())
    with TestClient(server.app) as client, TestClient(server.app) as other:
        uid = client.post('/api/upload', files=[('files', ('known.fcs', fcs()))]).json()['samples'][0]['id']
        spec = {'sample_ids': [uid], 'x': {'channel': 'X'}, 'y': {'channel': 'Y'}}
        template = client.post('/api/experiment-template', json=spec).json()
        assert template['samples'][0]['sample_id'] == hashlib.sha256(fcs()).hexdigest()
        template['samples'][0]['condition'] = '<script>alert(1)</script>'
        response = client.post('/api/export/experiment', json={'analysis': spec, 'manifest': template})
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            experiment = json.loads(archive.read('05-report/experiment.json'))
            assert experiment['samples'][0]['selected_count'] == 6
            assert experiment['producer']['name'] == 'aureka-flow'
            assert experiment['producer']['version'] == '0.5.0'
            html = archive.read('05-report/report.html').decode()
            assert '&lt;script&gt;' in html and '<script>' not in html
            receipt = json.loads(archive.read('run-receipt.json'))
            assert receipt['execution_path'] == 'browser_saved_population'
            assert next(m for m in receipt['modules'] if m['id'] == 'sortseq')['status'] == 'not_run'
            for item in receipt['files']:
                assert hashlib.sha256(archive.read(item['path'])).hexdigest() == item['sha256']
            assert {item['path'] for item in receipt['files']} == set(archive.namelist()) - {'run-receipt.json'}
        assert client.get('/api/qc/' + uid).json()['time']['backward_steps'] == 1
        assert other.get('/api/qc/' + uid).status_code == 422
        assert other.post('/api/experiment-template', json=spec).status_code == 422
        assert other.post('/api/export/experiment', json={'analysis': spec}).status_code == 422
        assert client.post('/api/export/experiment', json={'analysis': spec, 'manifest': {}}).status_code == 422
