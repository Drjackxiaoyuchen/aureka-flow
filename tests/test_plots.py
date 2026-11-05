"""Full-event single-channel histograms and true one-dimensional gate exports."""
import io
import json
import zipfile

import flowio
import flowkit as fk
import numpy as np
import pytest
from fastapi.testclient import TestClient

from aureka_flow import server
from aureka_flow.engine import AnalysisEngine, AxisSpec, ComparisonSpec, GateSpec, ProjectSpec, TransformSpec, ViewSpec
from aureka_flow.sessions import SessionStore


def one_channel(values):
    buffer=io.BytesIO()
    flowio.create_fcs(buffer,list(values),['Signal-A'])
    engine=AnalysisEngine()
    uid=engine.load(buffer.getvalue(),'one-channel.fcs')['id']
    return engine,uid,AxisSpec(channel='Signal-A')


def test_histogram_counts_every_event_despite_display_sampling_and_bin_changes():
    values=np.arange(1000,dtype=float)
    engine,uid,x=one_channel(values)
    for bins in (8,64,128,512):
        view=engine.view(ViewSpec(sample_id=uid,x=x,plot_type='histogram',max_points=100,histogram_bins=bins))
        h=view['histogram']
        expected,edges=np.histogram(values,bins=np.linspace(0,999,bins+1))
        assert view['population_count']==view['display_count']==1000
        assert h['counts']==expected.tolist() and h['edges']==edges.tolist()
        assert sum(h['counts'])==1000 and sum(h['percent'])==pytest.approx(100)
        assert view['median_x']==499.5 and view['median_y'] is None


@pytest.mark.parametrize('kind',['linear','logicle','asinh'])
def test_histogram_range_has_only_one_axis_and_roundtrips_through_gatingml(kind):
    engine,uid,_=one_channel([0,1,2,3,4,5])
    x=AxisSpec(channel='Signal-A',transform=TransformSpec(kind=kind))
    transform=x.transform.build()
    bounds=transform.apply(np.array([1.,4.])).tolist() if transform else [1.,4.]
    gate=GateSpec(name='Selected range',kind='range',x=x,bounds=[*bounds,None,None])
    assert engine.add_gate(gate,uid)['count']==3
    assert engine.mask(engine.record(uid),gate.name).tolist()==[False,True,True,True,False,False]
    view=engine.view(ViewSpec(sample_id=uid,x=x,plot_type='histogram',population=gate.name))
    assert sum(view['histogram']['counts'])==3
    xml,mapping=engine.gatingml()
    imported=fk.parse_gating_xml(io.BytesIO(xml))
    assert len(imported.get_gate(mapping[gate.name]).dimensions)==1
    result=imported.gate_sample(engine.record(uid).sample)
    assert result.get_gate_count(mapping[gate.name])==3
    project=ProjectSpec.model_validate(engine.project())
    assert project.schema_version==2 and project.gates[0].y is None
    row=engine.compare(ComparisonSpec(sample_ids=[uid],x=x,population=gate.name))['rows'][0]
    assert row['count']==3 and row['y_channel'] is None and row['median_y'] is None


def test_empty_constant_and_nonfinite_histograms():
    engine,uid,x=one_channel([5.,5.,5.,5.])
    engine.events(engine.record(uid),'raw')[0,0]=np.nan
    view=engine.view(ViewSpec(sample_id=uid,x=x,plot_type='histogram'))
    assert view['population_count']==4 and view['nonfinite_count']==1
    assert view['histogram']['finite_count']==sum(view['histogram']['counts'])==3
    assert view['median_x']==5
    engine.add_gate(GateSpec(name='Empty',kind='range',x=x,bounds=[10,20,None,None]),uid)
    empty=engine.view(ViewSpec(sample_id=uid,x=x,plot_type='histogram',population='Empty'))
    assert sum(empty['histogram']['counts'])==sum(empty['histogram']['percent'])==0
    assert empty['median_x'] is None


def test_histogram_api_and_event_export_do_not_require_a_dummy_y_channel(monkeypatch):
    engine,uid,x=one_channel([0,1,2,3,4])
    monkeypatch.setattr(server,'sessions',SessionStore(factory=lambda:engine))
    with TestClient(server.app) as client:
        assert 'histogram' in client.get('/api/state').json()['capabilities']['plot_types']
        body={'sample_id':uid,'x':x.model_dump(),'plot_type':'histogram','histogram_bins':32}
        view=client.post('/api/view',json=body)
        assert view.status_code==200 and sum(view.json()['histogram']['counts'])==5
        gate=GateSpec(name='Range',kind='range',x=x,bounds=[1,4,None,None])
        assert client.post('/api/gates',params={'sample_id':uid},json=gate.model_dump()).json()['count']==3
        events=client.post('/api/export/events',json=body|{'population':'Range'})
        assert events.status_code==200 and len(events.text.splitlines())==4
        spec={'sample_ids':[uid],'x':x.model_dump(),'population':'Range'}
        bundle=client.post('/api/export/bundle',json=spec)
        assert bundle.status_code==200
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            project=json.loads(archive.read('project.json'))
            assert project['schema_version']==2 and project['gates'][0]['y'] is None
            event_file=next(name for name in archive.namelist() if name.startswith('events/'))
            assert len(archive.read(event_file).decode().splitlines())==4
        assert client.post('/api/project',json=project).json()['gates']==1
        restored=client.post('/api/view',json=body|{'population':'Range'}).json()
        assert restored['population_count']==3


def test_invalid_range_cannot_accidentally_gate_counts_or_a_second_channel():
    x=AxisSpec(channel='Signal-A')
    with pytest.raises(ValueError):GateSpec(name='Bad',kind='range',x=x,bounds=[1,4,0,10])
    with pytest.raises(ValueError):GateSpec(name='Bad',kind='range',x=x,y=AxisSpec(channel='Count'),bounds=[1,4,None,None])
    with pytest.raises(ValueError):ViewSpec(sample_id='missing',x=x)  # scatter needs Y
