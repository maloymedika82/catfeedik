import os
import time
from sqlalchemy import select,func
import pytest
from backend.db import User,Points,Sponsor,SponsorTask,TaskApplication,Audit
from .test_app import setup,login
from .test_administration import moderator


def sponsor_payload(key='sponsor-create-12345',**changes):
    return {'request_key':key,'name':'Community Partner','description':'Support for local animal feeding volunteers.',
            'logo_url':'','active':True,'reason':'Approved partnership',**changes}


def task_payload(key='task-create-12345',**changes):
    return {'request_key':key,'title':'Describe your help','conditions':'Describe your completed help and provide a public link if requested.',
            'reward_points':15,'deadline_at':int(time.time())+3600,'active':True,'reason':'Launch manual task',**changes}


def create_pair(client,owner):
    s=client.post('/api/admin/sponsors',headers=owner,json=sponsor_payload())
    assert s.status_code==200,s.text
    t=client.post(f"/api/admin/sponsors/{s.json()['id']}/tasks",headers=owner,json=task_payload())
    assert t.status_code==200,t.text
    return s.json(),t.json()


def apply(client,headers,task,key='application-create-12345',**changes):
    return client.post(f"/api/tasks/{task['id']}/applications",headers=headers,json={'request_key':key,'terms_hash':task['terms_hash'],
         'evidence':'I completed the described help and documented the activity.','evidence_url':'https://example.org/proof',**changes})


def test_only_owner_can_manage_or_review_tasks(setup,monkeypatch):
    client,factory=setup;user=login(client);admin=moderator(client,factory,monkeypatch);owner=moderator(client,factory,monkeypatch,900,True)
    assert client.post('/api/admin/sponsors',headers=user,json=sponsor_payload()).status_code==403
    assert client.post('/api/admin/sponsors',headers=admin,json=sponsor_payload()).status_code==403
    assert client.get('/api/admin/sponsors',headers=admin).status_code==403
    assert client.get('/api/admin/task-applications',headers=admin).status_code==403
    _,task=create_pair(client,owner)
    claim=apply(client,user,task).json()
    assert client.post(f"/api/admin/task-applications/{claim['id']}/decision",headers=admin,json={'decision':'APPROVED','reason':'Cannot confirm as Admin'}).status_code==403
    assert client.get('/api/config').json()['money_enabled'] is False


def test_creation_retries_immutable_fingerprints_and_current_edit(setup,monkeypatch):
    client,factory=setup;owner=moderator(client,factory,monkeypatch,900,True)
    body=sponsor_payload();first=client.post('/api/admin/sponsors',headers=owner,json=body)
    assert client.post('/api/admin/sponsors',headers=owner,json=body).json()==first.json()
    assert client.post('/api/admin/sponsors',headers=owner,json={**body,'name':'Changed duplicate'}).status_code==409
    edited={k:v for k,v in body.items() if k!='request_key'};edited['name']='Renamed Partner';edited['reason']='Partner rebranding'
    assert client.put(f"/api/admin/sponsors/{first.json()['id']}",headers=owner,json=edited).status_code==200
    replay=client.post('/api/admin/sponsors',headers=owner,json=body)
    assert replay.status_code==200 and replay.json()['id']==first.json()['id'] and replay.json()['name']=='Renamed Partner'
    with factory() as db:assert db.scalar(select(func.count()).select_from(Sponsor))==1


def test_public_visibility_expiry_and_disabled_tasks(setup,monkeypatch):
    client,factory=setup;owner=moderator(client,factory,monkeypatch,900,True);user=login(client)
    sponsor,task=create_pair(client,owner)
    public=client.get('/api/sponsors').json()['items']
    assert len(public)==1 and public[0]['tasks'][0]['id']==task['id']
    assert 'created_by' not in public[0] and 'request_fingerprint' not in public[0]
    edited={k:v for k,v in sponsor_payload().items() if k!='request_key'};edited['active']=False
    client.put(f"/api/admin/sponsors/{sponsor['id']}",headers=owner,json=edited)
    assert client.get('/api/sponsors').json()['items']==[]
    assert client.get(f"/api/sponsors/{sponsor['id']}/tasks").status_code==404
    assert apply(client,user,task).status_code==409
    edited['active']=True;client.put(f"/api/admin/sponsors/{sponsor['id']}",headers=owner,json=edited)
    monkeypatch.setattr('backend.sponsors.time.time',lambda:task['deadline_at']+1)
    assert client.get('/api/sponsors').json()['items'][0]['tasks']==[]
    assert apply(client,user,task).status_code==409


def test_application_repeat_and_exactly_once_reward(setup,monkeypatch):
    client,factory=setup;owner=moderator(client,factory,monkeypatch,900,True);user=login(client)
    _,task=create_pair(client,owner)
    first=apply(client,user,task);assert first.status_code==200,first.text
    item=first.json()
    assert apply(client,user,task).json()==item
    assert apply(client,user,task,evidence='A different description for same operation').status_code==409
    assert apply(client,user,task,key='different-request-key-12345').status_code==409
    assert client.get('/api/me',headers=user).json()['points']==0
    decision={'decision':'APPROVED','reason':'Completion checked manually'}
    result=client.post(f"/api/admin/task-applications/{item['id']}/decision",headers=owner,json=decision)
    assert result.status_code==200,result.text
    assert client.post(f"/api/admin/task-applications/{item['id']}/decision",headers=owner,json=decision).json()==result.json()
    assert apply(client,user,task,key='after-reward-request-12345').status_code==409
    me=client.get('/api/me',headers=user).json()
    assert me['points']==15 and me['feedings']==0
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Points))==1
        assert db.scalar(select(func.count()).select_from(TaskApplication))==1
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='TASK_APPLICATION_APPROVED'))==1


def test_rejection_can_resubmit_new_attempt_until_deadline(setup,monkeypatch):
    client,factory=setup;owner=moderator(client,factory,monkeypatch,900,True);user=login(client)
    _,task=create_pair(client,owner)
    first=apply(client,user,task).json()
    client.post(f"/api/admin/task-applications/{first['id']}/decision",headers=owner,json={'decision':'REJECTED','reason':'Please provide clearer evidence'})
    second=apply(client,user,task,key='resubmitted-attempt-12345',evidence='Here is corrected evidence of the completed help.')
    assert second.status_code==200 and second.json()['attempt']==2
    assert client.get('/api/me/task-statuses',headers=user).json()[0]['id']==second.json()['id']
    assert len(client.get('/api/me/task-applications',headers=user).json()['items'])==2
    assert client.get('/api/me',headers=user).json()['points']==0


def test_terms_cannot_change_after_application_and_stale_form_is_rejected(setup,monkeypatch):
    client,factory=setup;owner=moderator(client,factory,monkeypatch,900,True);user=login(client)
    sponsor,task=create_pair(client,owner)
    edit={k:v for k,v in task_payload().items() if k!='request_key'};edit['deadline_at']=task['deadline_at'];edit['reward_points']=20
    changed=client.put(f"/api/admin/tasks/{task['id']}",headers=owner,json=edit)
    assert changed.status_code==200
    assert apply(client,user,task).status_code==409
    task=changed.json();assert apply(client,user,task).status_code==200
    edit['reward_points']=25
    assert client.put(f"/api/admin/tasks/{task['id']}",headers=owner,json=edit).status_code==409
    edit['reward_points']=20;edit['active']=False
    assert client.put(f"/api/admin/tasks/{task['id']}",headers=owner,json=edit).status_code==200


def test_on_time_submission_survives_closure_and_reward_uses_snapshot(setup,monkeypatch):
    client,factory=setup;owner=moderator(client,factory,monkeypatch,900,True);user=login(client)
    sponsor,task=create_pair(client,owner);item=apply(client,user,task).json()
    edit={k:v for k,v in task_payload().items() if k!='request_key'};edit['deadline_at']=task['deadline_at'];edit['active']=False
    client.put(f"/api/admin/tasks/{task['id']}",headers=owner,json=edit)
    rename={k:v for k,v in sponsor_payload().items() if k!='request_key'};rename['name']='New partner name';rename['active']=False
    client.put(f"/api/admin/sponsors/{sponsor['id']}",headers=owner,json=rename)
    monkeypatch.setattr('backend.sponsors.time.time',lambda:task['deadline_at']+10)
    result=client.post(f"/api/admin/task-applications/{item['id']}/decision",headers=owner,json={'decision':'APPROVED','reason':'On time submission checked later'})
    assert result.status_code==200 and result.json()['reward_points']==15
    assert result.json()['sponsor_name']=='Community Partner'
    assert client.get('/api/me',headers=user).json()['points']==15


def test_frozen_user_cannot_apply_or_receive_task_reward(setup,monkeypatch):
    client,factory=setup;owner=moderator(client,factory,monkeypatch,900,True);user=login(client)
    _,task=create_pair(client,owner);uid=client.get('/api/me',headers=user).json()['id'];item=apply(client,user,task).json()
    client.post(f'/api/admin/users/{uid}/freeze',headers=owner,json={'frozen':True,'reason':'Account risk check'})
    assert apply(client,user,task,key='new-frozen-request-12345').status_code==403
    assert client.post(f"/api/admin/task-applications/{item['id']}/decision",headers=owner,json={'decision':'APPROVED','reason':'Must not award frozen user'}).status_code==403
    assert client.get('/api/me',headers=user).json()['points']==0
    assert client.get('/api/me/task-applications',headers=user).json()['items'][0]['status']=='PENDING'


def test_private_evidence_and_invalid_urls(setup,monkeypatch):
    client,factory=setup;owner=moderator(client,factory,monkeypatch,900,True);first=login(client)
    _,task=create_pair(client,owner)
    assert apply(client,first,task,evidence_url='javascript:alert(1)').status_code==422
    assert apply(client,first,task,evidence_url='http://example.org').status_code==422
    assert apply(client,first,task,evidence_url='https://name:password@example.org').status_code==422
    item=apply(client,first,task).json()
    admin=moderator(client,factory,monkeypatch,999)
    assert client.get('/api/admin/task-applications',headers=admin).status_code==403
    assert client.get('/api/me/task-applications',headers=admin).json()['items']==[]
    assert client.get('/api/me/task-statuses',headers=admin).json()==[]
    public=client.get('/api/sponsors').json()
    assert item['evidence'] not in str(public) and 'evidence_url' not in str(public)


def test_invalid_fields_whitespace_and_expired_creation(setup,monkeypatch):
    client,factory=setup;owner=moderator(client,factory,monkeypatch,900,True)
    for changes in ({'name':'   '},{'description':'          '},{'logo_url':'data:image/png;base64,test'},{'name':'Name\x00bad'}):
        assert client.post('/api/admin/sponsors',headers=owner,json=sponsor_payload(**changes)).status_code==422
    sponsor=client.post('/api/admin/sponsors',headers=owner,json=sponsor_payload()).json()
    assert client.post(f"/api/admin/sponsors/{sponsor['id']}/tasks",headers=owner,json=task_payload(deadline_at=int(time.time())-1)).status_code==422
    assert client.post(f"/api/admin/sponsors/{sponsor['id']}/tasks",headers=owner,json=task_payload(reward_points=0)).status_code==422


def test_concurrent_task_decision_awards_once(setup,monkeypatch):
    if not os.getenv('TEST_DATABASE_URL'):pytest.skip('PostgreSQL concurrency required')
    from concurrent.futures import ThreadPoolExecutor
    client,factory=setup;owner=moderator(client,factory,monkeypatch,900,True);user=login(client)
    _,task=create_pair(client,owner);item=apply(client,user,task).json()
    def decide(_):return client.post(f"/api/admin/task-applications/{item['id']}/decision",headers=owner,json={'decision':'APPROVED','reason':'Verified once concurrently'})
    with ThreadPoolExecutor(max_workers=2) as executor:result=list(executor.map(decide,range(2)))
    assert [r.status_code for r in result]==[200,200]
    assert client.get('/api/me',headers=user).json()['points']==15
    with factory() as db:assert db.scalar(select(func.count()).select_from(Points))==1


def test_public_and_history_pagination(setup,monkeypatch):
    client,factory=setup;owner=moderator(client,factory,monkeypatch,900,True);user=login(client)
    sponsor=client.post('/api/admin/sponsors',headers=owner,json=sponsor_payload()).json()
    for number in range(12):
        response=client.post(f"/api/admin/sponsors/{sponsor['id']}/tasks",headers=owner,json=task_payload(key=f'task-{number:020}',title=f'Task {number}'))
        assert response.status_code==200
    catalog=client.get('/api/sponsors').json()['items'][0]
    assert len(catalog['tasks'])==10 and catalog['tasks_has_more']
    rest=client.get(f"/api/sponsors/{sponsor['id']}/tasks",params={'offset':10}).json()
    assert len(rest['items'])==2 and not rest['has_more']
    assert not {t['id'] for t in rest['items']} & {t['id'] for t in catalog['tasks']}
    assert client.get('/api/me/task-applications',headers=user,params={'limit':0}).status_code==422
