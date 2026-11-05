"""Backgating, histogram normalization and batch-table exports against known events."""
import io
import json
import zipfile

import flowio
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from aureka_flow import server
from aureka_flow.engine import AnalysisEngine, AxisSpec, ComparisonSpec, GateSpec, ViewSpec
from aureka_flow.sessions import SessionStore


def fcs(values, channels=('X', 'Y')):
    buffer = io.BytesIO()
    flowio.create_fcs(buffer, np.asarray(values, dtype=float).ravel().tolist(), list(channels))
    return buffer.getvalue()


@pytest.fixture
def workspace():
    values = np.column_stack([np.arange(2000), 2000-np.arange(2000)])
    engine = AnalysisEngine()
    uid = engine.load(fcs(values), 'known.fcs')['id']
    x, y = AxisSpec(channel='X'), AxisSpec(channel='Y')
    engine.add_gate(GateSpec(name='Parent', kind='range', x=x, bounds=[100,1900,None,None]), uid)
    engine.add_gate(GateSpec(name='Rare child', parent='Parent', kind='range', x=x, bounds=[1750,1753,None,None]), uid)
    return engine, uid, x, y, values


def test_backgating_preserves_rare_population_and_uses_full_counts(workspace):
    engine, uid, x, y, _ = workspace
    spec = ViewSpec(sample_id=uid, x=x, y=y, population='Rare child', context_population='Parent', max_points=100)
    view = engine.view(spec)
    assert view['population_count'] == view['display_count'] == 3
    assert view['event_indices'] == [1750,1751,1752]  # independent foreground sampling
    assert view['context']['population_count'] == 1800
    assert view['context']['display_count'] == 100
    assert view['median_x'] == 1751 and view['median_y'] == 249
    assert engine.view(spec.model_copy(update={'context_population':'root'}))['context']['population_count'] == 2000
    for population, context in [('Parent','Rare child'), ('Parent','Parent'), ('root','root'), ('Rare child','missing')]:
        with pytest.raises(ValueError, match='strict ancestor'):
            engine.view(spec.model_copy(update={'population':population,'context_population':context}))


def test_backgate_histograms_share_edges_and_ancestor_percent_denominator(workspace):
    engine, uid, x, _, values = workspace
    view = engine.view(ViewSpec(sample_id=uid, x=x, plot_type='histogram', population='Rare child', context_population='Parent', histogram_bins=32))
    h, context = view['histogram'], view['context']['histogram']
    np.testing.assert_array_equal(h['counts'], np.histogram(values[1750:1753,0], bins=h['edges'])[0])
    np.testing.assert_array_equal(context['counts'], np.histogram(values[100:1900,0], bins=h['edges'])[0])
    assert sum(h['counts']) == 3 and sum(context['counts']) == 1800
    assert sum(h['percent']) == pytest.approx(100*3/1800)
    assert sum(context['percent']) == pytest.approx(100)
    assert h['finite_count'] == 3 and h['normalization_count'] == 1800
    assert h['edges'][0] == 100 and h['edges'][-1] == 1899


def test_backgate_percentage_excludes_nonfinite_context_values_without_changing_membership(workspace):
    engine, uid, _, y, _ = workspace
    engine.record(uid).sample.get_events(source='raw')[0,1] = np.nan
    view = engine.view(ViewSpec(sample_id=uid, x=y, plot_type='histogram', population='Rare child', context_population='root'))
    assert view['population_count']==3 and view['context']['population_count']==2000
    assert view['context']['nonfinite_count']==1
    assert view['histogram']['normalization_count']==1999
    assert sum(view['histogram']['percent'])==pytest.approx(100*3/1999)


def test_overlay_normalizations_and_common_bins_do_not_change_gate_statistics(workspace):
    engine, uid, x, y, values = workspace
    other = engine.load(fcs(values[:1000]), 'short.fcs')['id']
    for bins in [32,100,512]:
        result = engine.compare(ComparisonSpec(sample_ids=[uid,other], x=x, y=y, histogram_axis='x', histogram_bins=bins))
        assert [row['count'] for row in result['rows']] == [2000,1000]
        a, b = result['histograms']
        assert a['x'] == b['x'] and len(a['x']) == bins
        for hist, count in [(a,2000),(b,1000)]:
            assert sum(hist['counts']) == hist['finite_count'] == count
            assert sum(hist['percent']) == pytest.approx(100)
            assert max(hist['modal']) == 100
            np.testing.assert_allclose(hist['modal'], np.asarray(hist['counts'])*100/max(hist['counts']))
    empty = engine.compare(ComparisonSpec(sample_ids=[other], x=x, y=y, population='Rare child'))
    assert empty['histograms'] == [] and empty['rows'][0]['count'] == 0
    with pytest.raises(ValueError):
        ComparisonSpec(sample_ids=[uid], x=x, histogram_bins=513)


def test_population_table_keeps_paths_denominators_and_incompatible_samples(workspace):
    engine, uid, x, y, values = workspace
    other = engine.load(fcs(values[:1000]), 'short.fcs')['id']
    bad = engine.load(fcs(values[:5], channels=('OTHER','Y')), 'incompatible.fcs')['id']
    result = engine.population_table(ComparisonSpec(sample_ids=[uid,other,bad], x=x, y=y))['rows']
    rows = [row for row in result if row['sample_id']==uid]
    assert [row['count'] for row in rows] == [2000,1800,3]
    child = rows[-1]
    assert child['path'] == 'All events / Parent / Rare child'
    assert child['percent_total'] == pytest.approx(100*3/2000)
    assert child['percent_parent'] == pytest.approx(100*3/1800)
    assert child['median_x'] == 1751 and child['median_y'] == 249
    assert child['sha256'] == engine.record(uid).digest and json.loads(child['x_transform'])['kind']=='linear'
    assert result[-1]['sample_id']==bad and 'missing channel' in result[-1]['error']
    histogram_rows = engine.population_table(ComparisonSpec(sample_ids=[uid], x=x))['rows']
    assert all(row['y_channel'] is None and row['median_y'] is None for row in histogram_rows)


def test_new_apis_keep_session_isolation_and_export_selected_events_only(monkeypatch):
    monkeypatch.setattr(server, 'sessions', SessionStore())
    with TestClient(server.app) as a, TestClient(server.app) as b:
        uid = a.post('/api/upload', files=[('files',('known.fcs',fcs([[i,i*2] for i in range(10)])))]).json()['samples'][0]['id']
        gate = {'name':'Child','kind':'range','x':{'channel':'X'},'bounds':[2,5,None,None]}
        assert a.post('/api/gates', params={'sample_id':uid}, json=gate).json()['count']==3
        view = {'sample_id':uid,'x':{'channel':'X'},'y':{'channel':'Y'},'population':'Child','context_population':'root'}
        assert a.post('/api/view', json=view).json()['context']['population_count']==10
        events = a.post('/api/export/events', json=view)
        assert pd.read_csv(io.StringIO(events.text))['event_index_zero_based'].tolist()==[2,3,4]
        spec = {'sample_ids':[uid],'x':{'channel':'X'},'y':{'channel':'Y'},'population':'Child','histogram_bins':32}
        rows = a.post('/api/population-table', json=spec).json()['rows']
        assert [row['count'] for row in rows]==[10,3]
        assert len(pd.read_csv(io.StringIO(a.post('/api/export/population-table', json=spec).text)))==2
        for endpoint in ['/api/population-table','/api/export/population-table']:
            assert b.post(endpoint, json=spec).status_code==422
        bundle = a.post('/api/export/bundle?include_population_table=true', json=spec)
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            assert len(pd.read_csv(io.BytesIO(archive.read('all-populations.csv'))))==2
            assert json.loads(archive.read('manifest.json'))['all_populations_included']
            name = next(name for name in archive.namelist() if name.startswith('events/'))
            assert pd.read_csv(io.BytesIO(archive.read(name)))['event_index_zero_based'].tolist()==[2,3,4]
