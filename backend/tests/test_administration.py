import os
import time
import pytest
from sqlalchemy import select,func
from backend.db import User,Points,PointAdjustment,Audit,Appeal,VideoAsset,AICheck,AIRetry,ProviderGate
from backend.ai import ProviderUnavailable
from backend.ai_control import reserve_request,next_provider_time
from backend.processing import process_video,retry_ai
from .test_app import setup,login,signed,seed_feeding
from .test_processing import real_video,upload_video,verdict


def moderator(client,factory,monkeypatch,identity=999,owner=False):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test-bot-token')
    if owner:monkeypatch.setenv('OWNER_TELEGRAM_IDS',str(identity))
    with factory() as db:
        user=db.scalar(select(User).where(User.telegram_id==identity))
        if not user:
            user=User(telegram_id=identity,name=f'Moderator {identity}',role='ADMIN');db.add(user);db.commit()
    response=client.post('/api/auth/telegram',json={'init_data':signed({'id':identity,'first_name':f'Moderator {identity}'})})
    assert response.status_code==200
    return {'Authorization':'Bearer '+response.json()['access_token']}


def test_admin_access_dev_session_and_owner_permissions(setup,monkeypatch):
    client,factory=setup;user=login(client)
    assert client.get('/api/admin/dashboard',headers=user).status_code==403
    assert client.get('/api/admin/dashboard').status_code==401
    response=client.post('/api/auth/dev-admin')
    assert response.status_code==200 and response.json()['user']['role']=='ADMIN'
    headers={'Authorization':'Bearer '+response.json()['access_token']}
    assert client.get('/api/admin/dashboard',headers=headers).status_code==200
    assert client.patch('/api/admin/ai',headers=headers,json={'enabled':False,'reason':'Maintenance'}).status_code==403
    monkeypatch.setenv('APP_ENV','production')
    assert client.post('/api/auth/dev-admin').status_code==404
    assert client.get('/api/admin/dashboard',headers=headers).status_code==401
    assert client.get('/api/me',headers=user).status_code==401


def test_points_receipt_retry_balance_and_audit(setup,monkeypatch):
    client,factory=setup;headers=login(client);target=client.get('/api/me',headers=headers).json()['id']
    admin=moderator(client,factory,monkeypatch)
    body={'request_key':'manual-points-request-12345','delta':25,'reason':'Correction after review'}
    first=client.post(f'/api/admin/users/{target}/points',headers=admin,json=body)
    assert first.status_code==200 and first.json()['old_balance']==0 and first.json()['new_balance']==25
    assert client.post(f'/api/admin/users/{target}/points',headers=admin,json=body).json()==first.json()
    assert client.post(f'/api/admin/users/{target}/points',headers=admin,json={**body,'delta':30}).status_code==409
    assert client.post(f'/api/admin/users/{target}/points',headers=admin,json={**body,'request_key':'second-operation-12345','delta':-30}).status_code==409
    assert client.post(f'/api/admin/users/{target}/points',headers=admin,json={**body,'request_key':'whitespace-operation-123','reason':'    '}).status_code==422
    assert client.get('/api/me',headers=headers).json()['points']==25
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PointAdjustment))==1
        assert db.scalar(select(func.count()).select_from(Points))==1
        audit=db.scalar(select(Audit).where(Audit.action=='POINTS_ADJUSTED'))
        assert 'old_balance' in audit.reason and 'new_balance' in audit.reason


def test_users_search_role_change_and_no_owner_demotion(setup,monkeypatch):
    client,factory=setup;headers=login(client);target=client.get('/api/me',headers=headers).json()['id']
    admin=moderator(client,factory,monkeypatch)
    owner=moderator(client,factory,monkeypatch,900,True)
    assert client.get('/api/admin/users',headers=admin,params={'q':'-1'}).json()['items'][0]['id']==target
    assert client.get('/api/admin/users',headers=admin,params={'q':'9'*100}).status_code==200
    assert client.patch(f'/api/admin/users/{target}/role',headers=admin,json={'role':'ADMIN','reason':'New moderator'}).status_code==403
    assert client.patch(f'/api/admin/users/{target}/role',headers=owner,json={'role':'ADMIN','reason':'New moderator'}).status_code==200
    assert client.get('/api/admin/dashboard',headers=headers).status_code==200
    assert client.patch(f'/api/admin/users/{target}/role',headers=owner,json={'role':'USER','reason':'Role removed'}).status_code==200
    assert client.get('/api/admin/dashboard',headers=headers).status_code==403
    oid=client.get('/api/me',headers=owner).json()['id']
    assert client.patch(f'/api/admin/users/{oid}/role',headers=owner,json={'role':'USER','reason':'Cannot demote owner'}).status_code==403


def rejection(client,factory,monkeypatch,headers):
    user=client.get('/api/me',headers=headers).json()['id']
    fid,_=seed_feeding(factory,user)
    original=moderator(client,factory,monkeypatch)
    response=client.post(f'/api/admin/feedings/{fid}/decision',headers=original,json={'decision':'REJECTED','reason':'Original decision'})
    assert response.status_code==200
    return fid,original


def test_appeal_other_admin_only_idempotent_and_once_award(setup,monkeypatch):
    client,factory=setup;headers=login(client)
    fid,original=rejection(client,factory,monkeypatch,headers)
    body={'reason':'Please review the feeding again'}
    opened=client.post(f'/api/feedings/{fid}/appeal',headers=headers,json=body)
    assert opened.status_code==200
    aid=opened.json()['id']
    assert client.post(f'/api/feedings/{fid}/appeal',headers=headers,json=body).json()==opened.json()
    assert client.post(f'/api/feedings/{fid}/appeal',headers=headers,json={'reason':'Change submitted reason'}).status_code==409
    assert client.post(f'/api/admin/appeals/{aid}/claim',headers=original).status_code==403
    reviewer=moderator(client,factory,monkeypatch,1000)
    assert client.post(f'/api/admin/appeals/{aid}/claim',headers=reviewer).status_code==200
    decision={'decision':'ACCEPTED','reason':'Video verified again'}
    assert client.post(f'/api/admin/appeals/{aid}/decision',headers=original,json=decision).status_code==403
    response=client.post(f'/api/admin/appeals/{aid}/decision',headers=reviewer,json=decision)
    assert response.status_code==200 and response.json()['feeding_status']=='APPROVED'
    assert client.post(f'/api/admin/appeals/{aid}/decision',headers=reviewer,json=decision).status_code==409
    assert client.get('/api/me',headers=headers).json()['points']==10
    assert client.get('/api/me/appeals',headers=headers).json()[0]['status']=='ACCEPTED'
    with factory() as db:assert db.scalar(select(func.count()).select_from(Appeal))==1


def test_appeal_invalid_video_and_foreign_user_protected(setup,monkeypatch):
    client,factory=setup;headers=login(client);fid,original=rejection(client,factory,monkeypatch,headers)
    reviewer=moderator(client,factory,monkeypatch,1000)
    assert client.post(f'/api/feedings/{fid}/appeal',headers=reviewer,json={'reason':'This is not my own video'}).status_code==404
    aid=client.post(f'/api/feedings/{fid}/appeal',headers=headers,json={'reason':'Please reconsider my feeding'}).json()['id']
    client.post(f'/api/admin/appeals/{aid}/claim',headers=reviewer)
    with factory() as db:db.get(VideoAsset,fid).status='INVALID';db.commit()
    assert client.post(f'/api/admin/appeals/{aid}/decision',headers=reviewer,json={'decision':'ACCEPTED','reason':'Cannot bypass validation'}).status_code==409
    assert client.get('/api/me',headers=headers).json()['points']==0


def test_429_global_gate_respects_retry_after_without_burning_attempts(setup,real_video,monkeypatch):
    client,factory=setup;headers=login(client)
    monkeypatch.setenv('AI_API_KEY','local-unit-test-key')
    monkeypatch.setattr('backend.processing.configured',lambda:True)
    clock=[int(time.time())]
    monkeypatch.setattr('backend.ai_control.time.time',lambda:clock[0])
    calls=[]
    def unavailable(_):
        calls.append(True)
        raise ProviderUnavailable('limited',{'status':429,'category':'request_rate_limit','retry_after_seconds':120})
    monkeypatch.setattr('backend.processing.moderate',unavailable)
    fid=upload_video(client,headers,real_video)
    assert process_video(fid,factory)['feeding_status']=='REVIEW'
    with factory() as db:
        assert db.get(AIRetry,fid).not_before==clock[0]+120
        assert next_provider_time(db)==clock[0]+120
        assert db.get(AICheck,fid).attempts==1
        assert 'local-unit-test-key' not in db.scalar(select(ProviderGate.scope))
    assert reserve_request(factory)==clock[0]+120
    clock[0]+=60
    assert retry_ai(fid,factory)['status']=='deferred' and len(calls)==1
    with factory() as db:assert db.get(AICheck,fid).attempts==1
    clock[0]+=60
    monkeypatch.setattr('backend.processing.moderate',lambda frames:(calls.append(True) or verdict()))
    assert retry_ai(fid,factory)['feeding_status']=='APPROVED' and len(calls)==2
    assert client.get('/api/me',headers=headers).json()['points']==10


def test_owner_manual_mode_keeps_video_processing_and_blocks_ai(setup,real_video,monkeypatch):
    client,factory=setup;headers=login(client);owner=moderator(client,factory,monkeypatch,900,True)
    response=client.patch('/api/admin/ai',headers=owner,json={'enabled':False,'reason':'Provider outage, manual moderation'})
    assert response.status_code==200
    monkeypatch.setattr('backend.processing.configured',lambda:True)
    def unexpected(_):raise AssertionError('Must not call AI while paused')
    monkeypatch.setattr('backend.processing.moderate',unexpected)
    fid=upload_video(client,headers,real_video)
    assert process_video(fid,factory)=={'status':'READY','feeding_status':'REVIEW'}
    with factory() as db:assert db.get(AICheck,fid).status=='PAUSED'
    assert retry_ai(fid,factory)['status']=='paused'
    assert client.get('/api/config').json()['ai_moderation_enabled'] is False
    assert client.get('/api/admin/dashboard',headers=owner).json()['money_enabled'] is False


def test_manual_points_concurrent_duplicate_is_once(setup,monkeypatch):
    if not os.getenv('TEST_DATABASE_URL'):pytest.skip('PostgreSQL row locks required')
    from concurrent.futures import ThreadPoolExecutor
    client,factory=setup;headers=login(client);target=client.get('/api/me',headers=headers).json()['id']
    admin=moderator(client,factory,monkeypatch)
    def adjust(_):return client.post(f'/api/admin/users/{target}/points',headers=admin,json={'request_key':'concurrent-adjust-12345','delta':10,'reason':'Concurrency test'})
    with ThreadPoolExecutor(max_workers=2) as executor:responses=list(executor.map(adjust,range(2)))
    assert [r.status_code for r in responses]==[200,200]
    assert responses[0].json()['id']==responses[1].json()['id']
    assert client.get('/api/me',headers=headers).json()['points']==10


def test_shared_provider_gate_concurrent_reservation_is_atomic(setup,monkeypatch):
    if not os.getenv('TEST_DATABASE_URL'):pytest.skip('PostgreSQL advisory locks required')
    from concurrent.futures import ThreadPoolExecutor
    _,factory=setup
    monkeypatch.setenv('AI_API_KEY','local-unit-test-key')
    now=int(time.time());monkeypatch.setattr('backend.ai_control.time.time',lambda:now)
    with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(lambda _:reserve_request(factory),range(2)))
    assert sorted(results)==[0,now+1]


def test_pause_during_ai_response_prevents_automatic_award(setup,real_video,monkeypatch):
    from backend.db import RuntimeControl
    client,factory=setup;headers=login(client)
    monkeypatch.setattr('backend.processing.configured',lambda:True)
    def pause_before_response(frames):
        with factory() as db:
            db.add(RuntimeControl(name='ai_enabled',value='0'));db.commit()
        return verdict()
    monkeypatch.setattr('backend.processing.moderate',pause_before_response)
    fid=upload_video(client,headers,real_video)
    assert process_video(fid,factory)['feeding_status']=='REVIEW'
    assert client.get('/api/me',headers=headers).json()['points']==0


def test_appeal_reprocessing_preserves_rejection_until_new_decision(setup,monkeypatch):
    from backend.db import Feeding
    client,factory=setup;headers=login(client);fid,original=rejection(client,factory,monkeypatch,headers)
    reviewer=moderator(client,factory,monkeypatch,1000)
    aid=client.post(f'/api/feedings/{fid}/appeal',headers=headers,json={'reason':'Please check technical processing again'}).json()['id']
    client.post(f'/api/admin/appeals/{aid}/claim',headers=reviewer)
    with factory() as db:db.get(VideoAsset,fid).status='ERROR';db.commit()
    url=f'/api/admin/appeals/{aid}/retry-processing'
    assert client.post(url,headers=original,json={'reason':'Original reviewer cannot retry appeal'}).status_code==403
    assert client.post(url,headers=reviewer,json={'reason':'FFmpeg configuration fixed'}).status_code==200
    with factory() as db:
        assert db.get(Feeding,fid).status=='REJECTED'
        assert db.get(VideoAsset,fid).status=='PENDING'
        assert db.scalar(select(Points)) is None


def test_frozen_account_cannot_gain_or_use_admin_permissions(setup,monkeypatch):
    client,factory=setup;headers=login(client);target=client.get('/api/me',headers=headers).json()['id']
    owner=moderator(client,factory,monkeypatch,900,True)
    assert client.post(f'/api/admin/users/{target}/freeze',headers=owner,json={'frozen':True,'reason':'Risk investigation'}).status_code==200
    assert client.patch(f'/api/admin/users/{target}/role',headers=owner,json={'role':'ADMIN','reason':'Premature promotion'}).status_code==409
    admin=moderator(client,factory,monkeypatch,999)
    with factory() as db:
        actor=db.scalar(select(User).where(User.telegram_id==999));actor.frozen=True;db.commit()
    assert client.get('/api/admin/dashboard',headers=admin).status_code==403
