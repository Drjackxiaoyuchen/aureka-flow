"""Independent synthetic byte fixtures; no instrument/hardware validation."""
import hashlib
import io
import json
import struct
import zipfile

import flowkit as fk
import numpy as np
import pytest
from fastapi.testclient import TestClient

from aureka_flow import server
from aureka_flow.engine import AnalysisEngine, GateSpec, ProjectSpec
from aureka_flow.fcs_import import read_fcs_text
from aureka_flow.sessions import SessionStore
from aureka_flow.workflows.core.core import analyze_fcs, inspect_fcs


EVENTS = np.array([[30., 6., 8.], [10., 2., 1.], [20., 4., 4.]])
NAMES = ['FITC$-A', 'FITC-A', 'Time']
SPILL = '2,FITC$-A,FITC-A,1,0.1,0.2,1'


def fcs(names=NAMES, *, delimiter='|', encoding='utf-8', extra=(), padding=0, overrides=None):
    """Write explicit HEADER/TEXT and little-endian floats without FlowIO."""
    end = 8192 + EVENTS.size * 4 - 1
    pairs = [('$BYTEORD', '1,2,3,4'), ('$DATATYPE', 'F'), ('$MODE', 'L'), ('$PAR', '3'),
             ('$TOT', '3'), ('$BEGINDATA', '8192'), ('$ENDDATA', str(end)), ('$NEXTDATA', '0'),
             ('$TIMESTEP', '0.25'), ('CREATOR', 'synthetic $ export'),
             ('$FIL', 'synthetic$source.fcs'), ('$SPILLOVER', SPILL)]
    for i, name in enumerate(names, 1):
        pairs += [(f'$P{i}N', name), (f'$P{i}B', '32'), (f'$P{i}R', '262144'), (f'$P{i}E', '0,0'),
                  (f'$P{i}G', '2' if i == 1 else '1'), (f'$P{i}S', 'Reporter$ café')]
    pairs = [(key, (overrides or {}).get(key, value)) for key, value in pairs]
    pairs += list(extra)
    text = (delimiter + delimiter.join(part.replace(delimiter, delimiter*2)
                                      for pair in pairs for part in pair) + delimiter).encode(encoding)
    text += b' ' * padding
    header = b'FCS3.1    ' + ''.join(f'{n:8d}' for n in (58, 57 + len(text), 8192, end, 0, 0)).encode('ascii')
    assert len(header) == 58 and len(header) + len(text) < 8192
    return header + text + b' ' * (8192 - len(header) - len(text)) + struct.pack('<9f', *EVENTS.ravel())


def config(names=NAMES, state='embedded'):
    return {'schema_version': 'yeast-facs-analysis-config/v1', 'sample_id': 'synthetic-text',
            'evidence_kind': 'synthetic', 'channels': names[:2],
            'compensation': {'state': state, 'reason': 'Synthetic reference equations'}}


def test_dollar_detector_collision_restored_before_gain_compensation_and_gating(tmp_path):
    data = fcs(extra=(('$P1S', 'invalid duplicate'),))
    # Even duplicate optional metadata is rejected, rather than silently chosen.
    with pytest.raises(ValueError, match='duplicate metadata'): AnalysisEngine().load(data, 'duplicate.fcs')
    data = fcs();engine = AnalysisEngine();info = engine.load(data, 'synthetic.fcs');rec = engine.record(info['id'])
    assert [c['id'] for c in info['channels']] == NAMES
    assert [c['stain'] for c in info['channels']] == ['Reporter$ café'] * 3
    assert [c['parameter_number'] for c in info['channels']] == [1, 2, 3]
    assert info['sha256'] == hashlib.sha256(data).hexdigest()
    expected = EVENTS / [2., 1., 4.]
    np.testing.assert_array_equal(engine.events(rec, 'raw'), expected)
    corrected = expected.copy();corrected[:, :2] = np.linalg.solve(np.array([[1., .1], [.2, 1.]]).T, expected[:, :2].T).T
    np.testing.assert_allclose(engine.events(rec, 'fcs'), corrected)
    assert rec.sample.metadata['creator'] == 'synthetic $ export'
    assert rec.sample.metadata['fil'] == 'synthetic$source.fcs'
    assert rec.sample.metadata['spillover'] == SPILL
    engine.add_gate(GateSpec(name='Literal channel', kind='range', x={'channel': NAMES[0]},
                             bounds=(8., 16., None, None), compensation='fcs'), info['id'])
    membership = (corrected[:, 0] >= 8.) & (corrected[:, 0] < 16.)
    np.testing.assert_array_equal(engine.mask(rec, 'Literal channel'), membership)
    project = engine.project();assert project['samples'][0]['fcs_metadata']['spillover'] == SPILL
    engine.restore_project(ProjectSpec.model_validate(project))
    xml, ids = engine.gatingml()
    replay = fk.parse_gating_xml(io.BytesIO(xml)).gate_sample(rec.sample)
    np.testing.assert_array_equal(replay.get_gate_membership(ids['Literal channel']), membership)
    path = tmp_path / 'synthetic.fcs';path.write_bytes(data)
    native = analyze_fcs(path, config())['samples'][0]
    for i, name in enumerate(NAMES[:2]): assert native['channels'][name]['median'] == pytest.approx(np.median(corrected[:, i]))
    assert native['processing']['embedded_spillover_sha256'] == hashlib.sha256(SPILL.encode()).hexdigest()
    assert native['processing']['source_compensation_state'] == 'unverified'
    assert path.read_bytes() == data


@pytest.mark.parametrize('delimiter', ['|', '/', '*', '\\', ':'])
def test_escaped_delimiters_unicode_and_value_spaces_remain_literal(tmp_path, delimiter):
    names = ['FL' + delimiter + '1$', 'FL2', 'Time']
    data = fcs(names, delimiter=delimiter, extra=(('NOTE', ' 值 $ / path | 末尾 '),), padding=64)
    info_engine = AnalysisEngine();info = info_engine.load(data, 'escaped.fcs');s = info_engine.record(info['id']).sample
    assert s.pnn_labels == names
    assert s.metadata['note'] == ' 值 $ / path | 末尾 '
    assert s.pns_labels == ['Reporter$ café'] * 3
    path = tmp_path / 'escaped.fcs';path.write_bytes(data)
    assert inspect_fcs(path)['channels'][0]['detector'] == names[0]
    native = analyze_fcs(path, config(names, 'uncompensated'))['samples'][0]
    assert native['channels'][names[0]]['median'] == 10.
    assert read_fcs_text(data)[1] == read_fcs_text(path)[1]


def test_legacy_latin1_values_and_literal_dollars_match_browser_and_native(tmp_path):
    data = fcs(encoding='latin-1')
    e = AnalysisEngine();info = e.load(data, 'legacy.fcs')
    assert info['channels'][0]['stain'] == 'Reporter$ café'
    path = tmp_path / 'legacy.fcs';path.write_bytes(data)
    assert inspect_fcs(path)['channels'][0]['detector'] == NAMES[0]
    assert analyze_fcs(path, config())['samples'][0]['selected_count'] == 3


@pytest.mark.parametrize('pair', [('$P1N', 'other'), ('$p1n', NAMES[0]), ('$P1G', '4'),
                                ('$SPILLOVER', SPILL), ('CREATOR', 'second')])
def test_duplicate_keywords_fail_before_workspace_mutation_in_both_paths(tmp_path, pair):
    data = fcs(extra=(pair,));e = AnalysisEngine()
    with pytest.raises(ValueError, match='duplicate metadata'): e.load(data, 'ambiguous.fcs')
    assert not e.samples
    path = tmp_path / 'ambiguous.fcs';path.write_bytes(data)
    with pytest.raises(ValueError, match='duplicate metadata'): analyze_fcs(path, config())


def test_literal_labels_and_source_order_survive_zip_intake_and_event_export(monkeypatch):
    monkeypatch.setattr(server, 'sessions', SessionStore())
    data = fcs();h = io.BytesIO()
    with zipfile.ZipFile(h, 'w') as z:
        z.writestr('valid.fcs', data)
        z.writestr('ambiguous.fcs', fcs(extra=(('$P1G', '4'),)))
    with TestClient(server.app) as c:
        result = c.post('/api/upload', files=[('files', ('synthetic.zip', h.getvalue()))]).json()
        assert len(result['samples']) == len(result['errors']) == 1
        assert 'ambiguous.fcs' in result['errors'][0]['filename']
        assert 'duplicate metadata' in result['errors'][0]['error']
        info = result['samples'][0];uid = info['id']
        assert [x['id'] for x in info['channels']] == NAMES
        source = c.get('/api/metadata/' + uid).json()
        assert source['fcs_metadata']['p1s'] == 'Reporter$ café'
        response = c.post('/api/export/bundle?include_events=true', json={
            'sample_ids': [uid], 'x': {'channel': NAMES[0]}, 'y': {'channel': NAMES[1]}, 'compensation': 'raw'})
        assert response.status_code == 200, response.text
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            sample = json.loads(z.read('project.json'))['samples'][0]
            assert sample['fcs_metadata']['p1n'] == NAMES[0]
            assert sample['source_containers'][0]['member_path'] == 'valid.fcs'
            csv = next(z.read(n).decode() for n in z.namelist() if n.startswith('events/'))
            import csv as csv_module
            rows = list(csv_module.DictReader(io.StringIO(csv)))
            assert [int(r['event_index_zero_based']) for r in rows] == [0, 1, 2]
            assert [float(r[NAMES[0]]) for r in rows] == [15., 5., 10.]
            assert all(r['source_sha256'] == hashlib.sha256(data).hexdigest() for r in rows)


def test_invalid_numeric_dollars_never_become_valid_decoding_metadata(tmp_path):
    # FlowIO 1.3.0 strips this dollar before interpreting P1B as 32.
    data = fcs(overrides={'$P1B': '3$2'})
    e = AnalysisEngine()
    with pytest.raises(ValueError, match='inconsistent DATA-decoding metadata'):
        e.load(data, 'invalid-bits.fcs')
    assert not e.samples
    path = tmp_path / 'invalid-bits.fcs';path.write_bytes(data)
    with pytest.raises(ValueError, match='inconsistent DATA-decoding metadata'):
        analyze_fcs(path, config())
