"""Session boundaries, resource accounting and actual analysis download contents."""
import io
import json
import zipfile

import flowio
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from aureka_flow import server
from aureka_flow.sessions import ServerBusy, SessionStore


def sample_bytes():
    handle = io.BytesIO()
    flowio.create_fcs(handle, [0, 0, 1, 1, 2, 2, 3, 3, 4, 4], ["X", "Y"])
    return handle.getvalue()


@pytest.fixture
def clients(monkeypatch):
    monkeypatch.setattr(server, "sessions", SessionStore())
    with TestClient(server.app) as first, TestClient(server.app) as second:
        yield first, second


def upload(client):
    return client.post('/api/upload', files=[('files', ('example.fcs', sample_bytes()))]).json()['samples'][0]['id']


def analysis(uid):
    return {'sample_id': uid, 'x': {'channel': 'X'}, 'y': {'channel': 'Y'}, 'population': 'Selected'}


def test_browser_workspaces_and_all_exports_are_separate(clients):
    a, b = clients
    uid = upload(a)
    gate = {'name':'Selected','kind':'rectangle','x':{'channel':'X'},'y':{'channel':'Y'},'bounds':[1,4,1,4]}
    assert a.post('/api/gates',params={'sample_id':uid},json=gate).json()['count']==3
    assert len(a.get('/api/state').json()['samples'])==1
    assert b.get('/api/state').json()['samples']==[]
    assert b.get('/api/project').json()['gates']==[]
    assert a.get('/api/state').json()['workspace']['id']!=b.get('/api/state').json()['workspace']['id']
    assert b.post('/api/view',json=analysis(uid)).status_code==422
    assert b.get('/api/metadata/'+uid).status_code==422
    assert b.get('/api/gatingml',params={'sample_id':uid}).status_code==422
    assert b.post('/api/export/events',json=analysis(uid)).status_code==422
    other = upload(b)
    assert other!=uid
    assert b.get('/api/project').json()['gates']==[]
    assert a.delete('/api/session').json()['cleared']
    assert len(b.get('/api/state').json()['samples'])==1


def test_zip_contains_full_membership_counts_and_provenance(clients):
    a,_=clients; uid=upload(a)
    gate={'name':'Selected','kind':'rectangle','x':{'channel':'X'},'y':{'channel':'Y'},'bounds':[1,4,1,4]}
    a.post('/api/gates',params={'sample_id':uid},json=gate)
    spec={k:v for k,v in analysis(uid).items() if k!='sample_id'}|{'sample_ids':[uid]}
    response=a.post('/api/export/bundle',json=spec)
    assert response.status_code==200
    assert response.headers['content-type']=='application/zip'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist())=={'project.json','population-statistics.csv','gates.xml','manifest.json','README.txt','events/01_example.csv'}
        stats=pd.read_csv(io.BytesIO(archive.read('population-statistics.csv')))
        events=pd.read_csv(io.BytesIO(archive.read('events/01_example.csv')))
        manifest=json.loads(archive.read('manifest.json'))
        assert stats['count'].iloc[0]==3 and stats['percent_parent'].iloc[0]==60
        assert events['event_index_zero_based'].tolist()==[1,2,3]
        assert events['X'].tolist()==[1,2,3]
        assert set(events['source_sha256'])=={manifest['sources'][0]['sha256']}
        assert json.loads(archive.read('project.json'))['gates'][0]['name']=='Selected'
    response=a.post('/api/export/bundle?include_events=false',json=spec)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert not any(n.startswith('events/') for n in archive.namelist())
    bad=a.post('/api/export/bundle',json=spec|{'sample_ids':['other-user-id']})
    assert bad.status_code==422


def test_cookie_fixation_origin_and_idle_capacity(clients):
    a,_=clients
    a.cookies.set('aureka_flow_web','attacker-chosen-token')
    response=a.get('/api/state')
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=lax' in response.headers['set-cookie']
    assert 'attacker-chosen-token' not in response.headers['set-cookie']
    assert response.headers['cache-control']=='no-store'
    assert a.post('/api/demo',headers={'Origin':'https://another.example'}).status_code==403
    assert a.post('/api/demo',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    now=[0.]
    store=SessionStore(ttl=10,max_sessions=1,clock=lambda:now[0])
    token,workspace=store.acquire(None)
    now[0]=20
    with pytest.raises(ServerBusy):store.acquire(None)  # in-flight work cannot expire
    store.release(workspace)
    now[0]=31
    replacement,other=store.acquire(token)
    assert replacement!=token and other is not workspace


def test_input_budget_duplicates_and_failed_parse_release_reservation(monkeypatch):
    data=sample_bytes()
    monkeypatch.setattr(server,'sessions',SessionStore(budget=len(data)))
    with TestClient(server.app) as a,TestClient(server.app) as b:
        uid=upload(a)
        assert upload(a)==uid  # duplicate succeeds even when the budget is exactly full
        failure=b.post('/api/upload',files=[('files',('other.fcs',data))]).json()
        assert failure['errors'] and failure['samples']==[]
        a.delete('/api/samples/'+uid)
        bad=b.post('/api/upload',files=[('files',('broken.fcs',b'not fcs'))]).json()
        assert bad['errors']
        assert all(w.reserved_bytes==0 for w in server.sessions.workspaces.values())
        assert upload(b)


def test_request_budget_rejects_declared_and_chunked_uploads(clients,monkeypatch):
    a,_=clients
    assert a.post('/api/upload',content=b'x',headers={'content-length':str(2**40)}).status_code==413
    monkeypatch.setattr(server.config,'MAX_FILE_BYTES',16)
    monkeypatch.setattr(server.config,'MAX_TOTAL_BYTES',16)
    def chunks():
        yield b'--test\r\nContent-Disposition: form-data; name="files"; filename="big.fcs"\r\nContent-Type: application/octet-stream\r\n\r\n'
        yield b'x'*(600*1024)
        yield b'x'*(600*1024)
        yield b'\r\n--test--\r\n'
    response=a.post('/api/upload',content=chunks(),headers={'content-type':'multipart/form-data; boundary=test'})
    assert response.status_code==413
