import os
import uuid
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend.auth import verify_init_data
from backend.db import Base, User, Feeding, Points, Audit, get_db
from backend.main import app

@pytest.fixture
def setup(monkeypatch):
    pg_url=os.getenv('TEST_DATABASE_URL')
    schema='test_'+uuid.uuid4().hex
    bootstrap=None
    if pg_url:
        bootstrap=create_engine(pg_url)
        with bootstrap.begin() as db:
            db.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(pg_url,connect_args={'options':f'-csearch_path={schema}'})
    else:
        engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    monkeypatch.setattr('backend.main.engine',engine)
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    def dependency():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db]=dependency
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.setenv('ALLOW_DEV_LOGIN','1')
    monkeypatch.setenv('LOCATION_RADIUS_METERS','100')
    monkeypatch.setenv('MAX_GPS_ACCURACY_METERS','50')
    monkeypatch.setenv('MAX_VIDEO_BYTES','1000000')
    with TestClient(app) as client:
        yield client,factory
    app.dependency_overrides.clear()
    engine.dispose()
    if bootstrap:
        with bootstrap.begin() as db:
            db.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        bootstrap.dispose()

def login(client):
    result=client.post('/api/auth/dev')
    assert result.status_code==200
    return {'Authorization':'Bearer '+result.json()['access_token']}

def signed(user=None,age=0):
    data={'auth_date':str(int(time.time())-age),'query_id':'example','user':json.dumps(user or {'id':81234,'first_name':'Аня'})}
    secret=hmac.new(b'WebAppData',b'test-bot-token',hashlib.sha256).digest()
    data['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
    return urlencode(data)

def seed_feeding(factory,user_id,number=0):
    with factory() as db:
        admin=db.scalar(select(User).where(User.telegram_id==999))
        if not admin:
            admin=User(telegram_id=999,name='Moderator',role='ADMIN');db.add(admin);db.flush()
        f=Feeding(user_id=user_id,request_key=f'test-request-{number:020}',city='Москва',latitude=55+number*.01,longitude=37,accuracy=10,mime_type='video/mp4',size=10,object_key=f'video-{number}',status='REVIEW',claimed_by=admin.id)
        db.add(f);db.commit()
        return f.id,admin.id

def admin_headers(client,factory,monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test-bot-token')
    data=signed({'id':999,'first_name':'Moderator'})
    result=client.post('/api/auth/telegram',json={'init_data':data})
    return {'Authorization':'Bearer '+result.json()['access_token']}

def test_signature_and_tampering():
    assert verify_init_data(signed(),'test-bot-token')['id']==81234
    with pytest.raises(ValueError):verify_init_data(signed().replace('81234','81235'),'test-bot-token')
    with pytest.raises(ValueError):verify_init_data(signed(age=4000),'test-bot-token')
    with pytest.raises(ValueError):verify_init_data(signed()+'&auth_date=1','test-bot-token')

def test_auth_required_and_dev_disabled(setup,monkeypatch):
    client,_=setup
    assert client.get('/api/me').status_code==401
    monkeypatch.setenv('APP_ENV','production')
    assert client.post('/api/auth/dev').status_code==404

def test_telegram_login_reuses_user_and_owner_is_server_config(setup,monkeypatch):
    client,factory=setup
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test-bot-token')
    monkeypatch.setenv('OWNER_TELEGRAM_IDS','81234')
    for _ in range(2):
        result=client.post('/api/auth/telegram',json={'init_data':signed()})
        assert result.status_code==200
        assert result.json()['user']['role']=='OWNER'
    with factory() as db:assert len(db.scalars(select(User)).all())==1
    assert client.post('/api/auth/telegram',json={'init_data':signed()+'x'}).status_code==401

def test_profile_persistence_and_logout(setup):
    client,_=setup;headers=login(client)
    r=client.patch('/api/me',headers=headers,json={'city':'Казань','language':'ru','wallet':'public-address'})
    assert r.status_code==200
    assert client.get('/api/me',headers=headers).json()['city']=='Казань'
    assert client.post('/api/auth/logout',headers=headers).status_code==204
    assert client.get('/api/me',headers=headers).status_code==401

def test_upload_retry_and_completion_are_idempotent(setup,monkeypatch):
    client,factory=setup;headers=login(client)
    storage=MagicMock();storage.generate_presigned_url.return_value='https://storage.example/signed'
    storage.head_object.return_value={'ContentLength':10,'ContentType':'video/mp4'}
    monkeypatch.setattr('backend.main.storage',lambda:storage)
    monkeypatch.setenv('R2_BUCKET','test')
    body=dict(request_key='same-request-key-12345',city='Москва',latitude=55.0,longitude=37.0,accuracy=10,mime_type='video/mp4',size=10)
    first=client.post('/api/feedings',headers=headers,json=body)
    assert first.status_code==200,first.text
    again=client.post('/api/feedings',headers=headers,json=body)
    assert again.json()['id']==first.json()['id']
    assert client.post('/api/feedings',headers=headers,json={**body,'size':11}).status_code==409
    for _ in range(2):
        result=client.post(f"/api/feedings/{first.json()['id']}/complete",headers=headers)
        assert result.json()['status']=='REVIEW'
    with factory() as db:
        assert len(db.scalars(select(Feeding)).all())==1
        assert len(db.scalars(select(Points)).all())==0

def test_missing_storage_does_not_create_feeding(setup,monkeypatch):
    client,factory=setup;headers=login(client)
    for name in ('R2_ENDPOINT_URL','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET'):monkeypatch.delenv(name,raising=False)
    result=client.post('/api/feedings',headers=headers,json=dict(request_key='missing-storage-12345',city='Москва',latitude=55,longitude=37,accuracy=10,mime_type='video/mp4',size=10))
    assert result.status_code==503
    with factory() as db:assert db.scalar(select(Feeding)) is None

def test_five_bonus_exactly_once_and_repeat_decision_rejected(setup,monkeypatch):
    client,factory=setup;headers=login(client)
    user=client.get('/api/me',headers=headers).json()
    first,_=seed_feeding(factory,user['id'])
    admin=admin_headers(client,factory,monkeypatch)
    ids=[first]+[seed_feeding(factory,user['id'],i)[0] for i in range(1,6)]
    for fid in ids:
        r=client.post(f'/api/admin/feedings/{fid}/decision',headers=admin,json={'decision':'APPROVED','reason':'Видео проверено вручную'})
        assert r.status_code==200,r.text
    r=client.post(f'/api/admin/feedings/{first}/decision',headers=admin,json={'decision':'APPROVED','reason':'Повтор'})
    assert r.status_code==409
    assert client.get('/api/me',headers=headers).json()['points']==65
    assert client.get('/api/me',headers=headers).json()['feedings']==6
    with factory() as db:
        assert len(db.scalars(select(Points).where(Points.delta==5)).all())==1
        assert len(db.scalars(select(Audit)).all())==6

def test_same_location_seven_day_rule_and_other_user_isolated(setup,monkeypatch):
    client,factory=setup;headers=login(client);user=client.get('/api/me',headers=headers).json()
    first,_=seed_feeding(factory,user['id'],0);second,_=seed_feeding(factory,user['id'],1)
    with factory() as db:
        db.get(Feeding,second).latitude=55.0;db.commit()
    admin=admin_headers(client,factory,monkeypatch)
    body={'decision':'APPROVED','reason':'Проверено'}
    assert client.post(f'/api/admin/feedings/{first}/decision',headers=admin,json=body).status_code==200
    assert client.post(f'/api/admin/feedings/{second}/decision',headers=admin,json=body).status_code==409
    with factory() as db:
        db.get(Feeding,first).created_at-=7*86400;db.commit()
    assert client.post(f'/api/admin/feedings/{second}/decision',headers=admin,json=body).status_code==200

def test_claim_is_exclusive_and_user_cannot_admin(setup,monkeypatch):
    client,factory=setup;headers=login(client);user=client.get('/api/me',headers=headers).json()
    fid,_=seed_feeding(factory,user['id'])
    with factory() as db:db.get(Feeding,fid).claimed_by=None;db.commit()
    assert client.get('/api/admin/queue',headers=headers).status_code==403
    admin=admin_headers(client,factory,monkeypatch)
    assert client.post(f'/api/admin/feedings/{fid}/claim',headers=admin).status_code==200
    assert client.post(f'/api/admin/feedings/{fid}/claim',headers=admin).status_code==409

def test_frozen_user_cannot_upload_or_save(setup):
    client,factory=setup;headers=login(client)
    with factory() as db:
        user=db.scalar(select(User).where(User.telegram_id==-1));user.frozen=True;db.commit()
    assert client.patch('/api/me',headers=headers,json={'city':'Москва','wallet':'','language':'ru'}).status_code==403

def test_approval_requires_agreed_location_rules(setup,monkeypatch):
    client,factory=setup;headers=login(client);user=client.get('/api/me',headers=headers).json()
    fid,_=seed_feeding(factory,user['id']);admin=admin_headers(client,factory,monkeypatch)
    monkeypatch.delenv('LOCATION_RADIUS_METERS')
    assert client.post(f'/api/admin/feedings/{fid}/decision',headers=admin,json={'decision':'APPROVED','reason':'Проверено'}).status_code==503
    assert client.get('/api/me',headers=headers).json()['points']==0

def test_snapshot_stays_fixed_within_hour_even_when_empty(setup):
    client,factory=setup
    assert client.get('/api/leaderboard').json()['items']==[]
    headers=login(client);user=client.get('/api/me',headers=headers).json()
    with factory() as db:
        db.add(Points(user_id=user['id'],event_key='test:one',delta=10,reason='Test'))
        db.commit()
    assert client.get('/api/leaderboard').json()['items']==[]

def test_freeze_rejects_pending_and_preserves_history(setup,monkeypatch):
    client,factory=setup;headers=login(client);user=client.get('/api/me',headers=headers).json()
    fid,_=seed_feeding(factory,user['id']);admin=admin_headers(client,factory,monkeypatch)
    r=client.post(f"/api/admin/users/{user['id']}/freeze",headers=admin,json={'frozen':True,'reason':'Ручная проверка риска'})
    assert r.status_code==200
    history=client.get('/api/me/feedings',headers=headers).json()
    assert history[0]['status']=='REJECTED'
    assert client.get('/api/me',headers=headers).json()['points']==0
    with factory() as db:assert len(db.scalars(select(Audit)).all())==1

def test_user_cannot_complete_another_users_upload(setup,monkeypatch):
    client,factory=setup;headers=login(client);user=client.get('/api/me',headers=headers).json()
    fid,_=seed_feeding(factory,user['id']);admin=admin_headers(client,factory,monkeypatch)
    assert client.post(f'/api/feedings/{fid}/complete',headers=admin).status_code==404


def test_concurrent_postgres_approval_is_once(setup,monkeypatch):
    if not os.getenv('TEST_DATABASE_URL'):
        pytest.skip('PostgreSQL required for row-lock concurrency test')
    from concurrent.futures import ThreadPoolExecutor
    client,factory=setup;headers=login(client);user=client.get('/api/me',headers=headers).json()
    fid,_=seed_feeding(factory,user['id']);admin=admin_headers(client,factory,monkeypatch)
    def decide():
        return client.post(f'/api/admin/feedings/{fid}/decision',headers=admin,json={'decision':'APPROVED','reason':'Конкурентная проверка'}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(lambda _:decide(),range(2)))
    assert sorted(results)==[200,409]
    assert client.get('/api/me',headers=headers).json()['points']==10
