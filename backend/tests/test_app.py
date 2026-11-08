import os
import uuid
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend.auth import verify_init_data
from backend.db import Base, User, Feeding, Points, Audit, VideoAsset, get_db
from backend.main import app

@pytest.fixture
def setup(monkeypatch,tmp_path):
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
    monkeypatch.setenv('VIDEO_STORAGE_DIR',str(tmp_path/'private-videos'))
    monkeypatch.setenv('VIDEO_MIN_FREE_BYTES','0')
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
    headers={'Authorization':'Bearer '+result.json()['access_token']}
    terms=client.get('/api/me/participation-consent',headers=headers).json()
    assert client.post('/api/me/participation-consent',headers=headers,json={k:terms[k] for k in ('version','document_hash')}|{'accepted':True}).status_code==200
    return headers

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
        db.add(f);db.flush()
        db.add(VideoAsset(feeding_id=f.id,status='READY',city_id='524901'))
        db.commit()
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
    body=dict(request_key='same-request-key-12345',city='Москва',latitude=55.0,longitude=37.0,accuracy=10,mime_type='video/mp4',size=10)
    first=client.post('/api/feedings',headers=headers,json=body)
    assert first.status_code==200,first.text
    again=client.post('/api/feedings',headers=headers,json=body)
    assert again.json()['id']==first.json()['id']
    assert client.post('/api/feedings',headers=headers,json={**body,'size':11}).status_code==409
    uploaded=client.put('/api'+first.json()['upload_path'],headers={**headers,'Content-Type':'video/mp4'},content=b'0123456789')
    assert uploaded.status_code==204,uploaded.text
    for _ in range(2):
        result=client.post(f"/api/feedings/{first.json()['id']}/complete",headers=headers)
        assert result.json()['status']=='PROCESSING'
    with factory() as db:
        assert len(db.scalars(select(Feeding)).all())==1
        assert len(db.scalars(select(Points)).all())==0

def test_one_submitted_video_per_hour_rejection_releases_pause(setup):
    client,factory=setup;headers=login(client)
    body=dict(city_id='524901',mime_type='video/mp4',size=10)
    first=client.post('/api/feedings',headers=headers,json={**body,'request_key':'hourly-first-1234567890'})
    assert first.status_code==200,first.text
    fid=first.json()['id']
    assert client.put('/api'+first.json()['upload_path'],headers={**headers,'Content-Type':'video/mp4'},content=b'0123456789').status_code==204
    assert client.post(f'/api/feedings/{fid}/complete',headers=headers).status_code==200
    blocked=client.post('/api/feedings',headers=headers,json={**body,'request_key':'hourly-second-1234567890'})
    assert blocked.status_code==429
    assert client.post('/api/feedings',headers=headers,json={**body,'request_key':'hourly-first-1234567890'}).json()['id']==fid
    with factory() as db:
        item=db.get(Feeding,fid)
        assert item.submitted_at>0
        item.status='REJECTED';db.commit()
    assert client.post('/api/feedings',headers=headers,json={**body,'request_key':'hourly-second-1234567890'}).status_code==200

def test_admin_video_history_includes_decided_videos(setup,monkeypatch):
    client,factory=setup;headers=login(client)
    uid=client.get('/api/me',headers=headers).json()['id']
    fid,_=seed_feeding(factory,uid)
    admin=admin_headers(client,factory,monkeypatch)
    assert client.post(f'/api/admin/feedings/{fid}/decision',headers=admin,
        json={'decision':'REJECTED','reason':'Нет кормления'}).status_code==200
    assert client.get('/api/admin/videos',headers=headers).status_code==403
    history=client.get('/api/admin/videos',headers=admin).json()
    assert history['items'][0]['id']==fid and history['items'][0]['status']=='REJECTED'

def test_missing_storage_does_not_create_feeding(setup,monkeypatch):
    client,factory=setup;headers=login(client)
    from fastapi import HTTPException
    def unavailable():
        raise HTTPException(503,'Каталог недоступен')
    monkeypatch.setattr('backend.main.storage_root',unavailable)
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

def test_same_city_does_not_block_separate_feedings(setup,monkeypatch):
    client,factory=setup;headers=login(client);user=client.get('/api/me',headers=headers).json()
    first,_=seed_feeding(factory,user['id'],0);second,_=seed_feeding(factory,user['id'],1)
    with factory() as db:
        db.get(Feeding,second).latitude=55.0;db.commit()
    admin=admin_headers(client,factory,monkeypatch)
    body={'decision':'APPROVED','reason':'Проверено'}
    assert client.post(f'/api/admin/feedings/{first}/decision',headers=admin,json=body).status_code==200
    assert client.post(f'/api/admin/feedings/{second}/decision',headers=admin,json=body).status_code==200
    assert client.get('/api/me',headers=headers).json()['points']==20

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

def test_approval_needs_no_gps_settings(setup,monkeypatch):
    client,factory=setup;headers=login(client);user=client.get('/api/me',headers=headers).json()
    fid,_=seed_feeding(factory,user['id']);admin=admin_headers(client,factory,monkeypatch)
    monkeypatch.delenv('LOCATION_RADIUS_METERS')
    monkeypatch.setenv('APP_ENV','production')
    assert client.post(f'/api/admin/feedings/{fid}/decision',headers=admin,json={'decision':'APPROVED','reason':'Проверено'}).status_code==200
    with factory() as db:assert db.scalar(select(Points)) is not None

def test_city_selection_never_stores_precise_coordinates(setup):
    client,factory=setup;headers=login(client)
    cities=client.get('/api/city-search',params={'q':'Москва'}).json()
    moscow=next(city for city in cities if city['id']=='524901')
    fresh=client.post('/api/feedings',headers=headers,json={
        'request_key':'city-only-upload-12345','city_id':moscow['id'],
        'mime_type':'video/mp4','size':10})
    assert fresh.status_code==200
    legacy=client.post('/api/feedings',headers=headers,json={
        'request_key':'legacy-location-12345','city':'ignored','latitude':55.750123,
        'longitude':37.610987,'accuracy':10,'mime_type':'video/mp4','size':10})
    assert legacy.status_code==200
    with factory() as db:
        for result in (fresh,legacy):
            feeding=db.get(Feeding,result.json()['id'])
            assert feeding.city_id==moscow['id']
            assert (feeding.latitude,feeding.longitude)==(moscow['latitude'],moscow['longitude'])
            assert feeding.accuracy==0
    assert client.post('/api/feedings',headers=headers,json={
        'request_key':'unknown-city-12345','city_id':'invalid','mime_type':'video/mp4','size':10}).status_code==422

def test_many_new_uploads_are_limited_but_retry_still_works(setup):
    client,_=setup;headers=login(client)
    first=None
    for number in range(12):
        payload={'request_key':f'rate-limit-{number:020}','city_id':'524901','mime_type':'video/mp4','size':10}
        response=client.post('/api/feedings',headers=headers,json=payload)
        assert response.status_code==200
        if number==0:first=(payload,response.json()['id'])
    assert client.post('/api/feedings',headers=headers,json={
        'request_key':'rate-limit-overflow-12345','city_id':'524901','mime_type':'video/mp4','size':10}).status_code==429
    assert client.post('/api/feedings',headers=headers,json=first[0]).json()['id']==first[1]

def test_snapshot_stays_fixed_within_hour_even_when_empty(setup):
    client,factory=setup
    assert client.get('/api/leaderboard').json()['items']==[]
    headers=login(client);user=client.get('/api/me',headers=headers).json()
    with factory() as db:
        db.add(Points(user_id=user['id'],event_key='test:one',delta=10,reason='Test'))
        db.commit()
    assert client.get('/api/leaderboard').json()['items']==[]

def test_personal_rank_uses_hourly_snapshot(setup):
    client,factory=setup;headers=login(client);user=client.get('/api/me',headers=headers).json()
    with factory() as db:
        other=User(telegram_id=7654321,name='Другой участник')
        db.add(other);db.flush()
        db.add(Points(user_id=user['id'],event_key='rank:own',delta=10,reason='Кормление'))
        db.add(Points(user_id=other.id,event_key='rank:other',delta=20,reason='Кормление'))
        db.commit()
    result=client.get('/api/me/rank',headers=headers)
    assert result.status_code==200
    assert result.json()['rank']==2
    assert result.json()['participants']==2
    assert result.json()['updated_at']==client.get('/api/leaderboard').json()['updated_at']

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


def create_upload(client,headers,size=10,key='local-upload-key-12345'):
    response=client.post('/api/feedings',headers=headers,json=dict(request_key=key,city='Москва',latitude=55,longitude=37,accuracy=10,mime_type='video/mp4',size=size))
    assert response.status_code==200,response.text
    return response.json()


def test_local_file_immutable_and_same_content_retry(setup):
    from backend.local_storage import object_path,storage_root
    client,factory=setup;headers=login(client)
    item=create_upload(client,headers)
    for _ in range(2):
        assert client.put('/api'+item['upload_path'],headers={**headers,'Content-Type':'video/mp4'},content=b'0123456789').status_code==204
    changed=client.put('/api'+item['upload_path'],headers={**headers,'Content-Type':'video/mp4'},content=b'9876543210')
    assert changed.status_code==409
    with factory() as db:
        feeding=db.get(Feeding,item['id'])
        assert object_path(feeding.object_key).read_bytes()==b'0123456789'
    assert list((storage_root()/'_incoming').iterdir())==[]


def test_stream_size_limit_and_partial_cleanup(setup):
    from backend.local_storage import storage_root
    client,_=setup;headers=login(client);item=create_upload(client,headers)
    for content,code in ((b'01234567890',413),(b'123',422)):
        response=client.put('/api'+item['upload_path'],headers={**headers,'Content-Type':'video/mp4'},content=iter([content]))
        assert response.status_code==code,response.text
        assert list((storage_root()/'_incoming').iterdir())==[]
    assert client.post(f"/api/feedings/{item['id']}/complete",headers=headers).status_code==409


def test_content_type_and_declared_size_rejected(setup):
    client,_=setup;headers=login(client);item=create_upload(client,headers)
    assert client.put('/api'+item['upload_path'],headers={**headers,'Content-Type':'text/html'},content=b'0123456789').status_code==415
    assert client.put('/api'+item['upload_path'],headers={**headers,'Content-Type':'video/mp4'},content=b'123').status_code==422


def test_local_media_cookie_ranges_access_and_logout(setup,monkeypatch):
    client,factory=setup;headers=login(client);item=create_upload(client,headers)
    assert client.put('/api'+item['upload_path'],headers={**headers,'Content-Type':'video/mp4'},content=b'0123456789').status_code==204
    assert client.get(f"/api/media/{item['id']}",headers=headers).status_code==409
    client.post(f"/api/feedings/{item['id']}/complete",headers=headers)
    media=client.get(f"/api/media/{item['id']}") # Browser video uses HttpOnly cookie.
    assert media.status_code==200 and media.content==b'0123456789'
    assert media.headers['cache-control']=='private, no-store'
    partial=client.get(f"/api/media/{item['id']}",headers={'Range':'bytes=2-5'})
    assert partial.status_code==206 and partial.content==b'2345'
    assert partial.headers['content-range']=='bytes 2-5/10'
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test-bot-token')
    other=client.post('/api/auth/telegram',json={'init_data':signed({'id':765432,'first_name':'Other'})}).json()
    other_headers={'Authorization':'Bearer '+other['access_token']}
    assert client.get(f"/api/media/{item['id']}",headers=other_headers).status_code==404
    assert client.put('/api'+item['upload_path'],headers={**other_headers,'Content-Type':'video/mp4'},content=b'0123456789').status_code==404
    with factory() as db:
        user=db.scalar(select(User).where(User.telegram_id==999))
        if not user:db.add(User(telegram_id=999,name='Moderator',role='ADMIN'));db.commit()
    admin=admin_headers(client,factory,monkeypatch)
    detail=client.get(f"/api/admin/feedings/{item['id']}",headers=admin)
    assert detail.status_code==200
    assert detail.json()['video_url']==f"/api/media/{item['id']}"
    assert client.get(detail.json()['video_url']).status_code==200
    client.post('/api/auth/logout',headers=admin)
    assert client.get(detail.json()['video_url']).status_code==401
    assert client.get(detail.json()['video_url'],headers=admin).status_code==401


def test_freeze_during_upload_prevents_publish(setup,monkeypatch):
    from backend.local_storage import storage_root
    client,factory=setup;headers=login(client);item=create_upload(client,headers)
    with factory() as db:
        user=db.scalar(select(User).where(User.telegram_id==-1));user.frozen=True;db.commit()
    response=client.put('/api'+item['upload_path'],headers={**headers,'Content-Type':'video/mp4'},content=b'0123456789')
    assert response.status_code==403
    assert not list(storage_root().glob('originals/**/*'))


def test_disk_reserve_rejects_new_sessions(setup,monkeypatch):
    from collections import namedtuple
    usage=namedtuple('usage','total used free')
    monkeypatch.setattr('backend.local_storage.shutil.disk_usage',lambda _:usage(100,99,1))
    client,factory=setup;headers=login(client)
    response=client.post('/api/feedings',headers=headers,json=dict(request_key='disk-space-key-12345',city='Москва',latitude=55,longitude=37,accuracy=10,mime_type='video/mp4',size=10))
    assert response.status_code==507
    with factory() as db:assert db.scalar(select(Feeding)) is None


def test_storage_path_escape_and_public_directory_rejected(setup,monkeypatch,tmp_path):
    from backend.local_storage import object_path,storage_root
    from fastapi import HTTPException
    for key in ('../secret','/etc/passwd','folder/../../secret','folder\\secret'):
        with pytest.raises(HTTPException):object_path(key)
    root=storage_root()
    outside=tmp_path/'outside';outside.mkdir()
    (root/'linked').symlink_to(outside,target_is_directory=True)
    with pytest.raises(HTTPException):object_path('linked/file')
    monkeypatch.setenv('VIDEO_STORAGE_DIR','public/videos')
    with pytest.raises(HTTPException):storage_root()


def test_startup_cleanup_only_old_staging_files(setup):
    from backend.local_storage import storage_root,cleanup_abandoned_uploads
    root=storage_root();old=root/'_incoming'/'old.part';fresh=root/'_incoming'/'fresh.part';original=root/'keep.mp4'
    for path in (old,fresh,original):path.write_bytes(b'test')
    os.utime(old,(time.time()-90000,time.time()-90000))
    abandoned=root/'_incoming'/'process-old';abandoned.mkdir();(abandoned/'frame.jpg').write_bytes(b'test')
    os.utime(abandoned,(time.time()-90000,time.time()-90000))
    cleanup_abandoned_uploads(root)
    assert not old.exists() and not abandoned.exists() and fresh.exists() and original.exists()


def test_freeze_while_receiving_body_prevents_publish(setup):
    from backend.local_storage import storage_root
    client,factory=setup;headers=login(client);item=create_upload(client,headers)
    def content():
        yield b'12345'
        with factory() as db:
            user=db.scalar(select(User).where(User.telegram_id==-1));user.frozen=True;db.commit()
        yield b'67890'
    response=client.put('/api'+item['upload_path'],headers={**headers,'Content-Type':'video/mp4'},content=content())
    assert response.status_code==403,response.text
    assert not list(storage_root().glob('originals/**/*'))
    assert list((storage_root()/'_incoming').iterdir())==[]


def test_concurrent_different_uploads_cannot_replace_original(setup):
    if not os.getenv('TEST_DATABASE_URL'):
        pytest.skip('PostgreSQL required for concurrent connections')
    from concurrent.futures import ThreadPoolExecutor
    from backend.local_storage import object_path,storage_root
    client,factory=setup;headers=login(client);item=create_upload(client,headers)
    bodies=[b'0123456789',b'9876543210']
    def put(body):
        return client.put('/api'+item['upload_path'],headers={**headers,'Content-Type':'video/mp4'},content=body).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(put,bodies))
    assert sorted(results)==[204,409]
    with factory() as db:
        feeding=db.get(Feeding,item['id'])
        assert object_path(feeding.object_key).read_bytes() in bodies
    assert list((storage_root()/'_incoming').iterdir())==[]
